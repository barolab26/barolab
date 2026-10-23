"""One exact, ledger-bound editor repair; uncertain submissions are verified only."""
import json
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
    rendered='\n'.join(page.locator('.se-canvas .se-text-paragraph').all_inner_texts())
    if kin._naver_browser__normalized(rendered)!=kin._naver_browser__normalized(document['answer_text']):
        raise ValueError('Editor differs from approved answer; preserved')
    links=page.locator('.se-canvas a[href], .se-canvas .se-link[data-href]').evaluate_all('es=>es.map(e=>e.href || e.getAttribute("data-href"))')
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
        before_submit()
        button.evaluate('(el) => { if(el.disabled || el.getAttribute("aria-disabled")==="true") throw new Error("disabled"); HTMLElement.prototype.click.call(el); }')
        for _ in range(30):
            page.wait_for_timeout(500)
            if result or dialogs:break
        if result:
            return {**result,'answer_url':kin._naver_browser_exact_answer_url(page.url,result['answer_id']),
                    'reason':'CDP click observed; public verification pending'}
        for text in dialogs:kin._naver_browser__check_protection_message(text)
        return {'reason':'Submission uncertain after one click; verification only; no retry'}
    finally:
        page.remove_listener('response',response_seen);page.remove_listener('dialog',dialog_seen)


def public_evidence(account,row,document):
    from naver_kin import posting as kin
    evidence=kin._naver_browser_verify_public(account,row['answer_url'],document['answer_text'],document['attribution']['outboundUrl'],row['answer_id'])
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
        with websocket.create_connection(address,timeout=10,suppress_origin=True) as ws:
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
    import datetime,fcntl,hashlib
    from common.runtime_locks import runtime_lock_path
    from common.collection_observability import write,locked,load
    from dashboard.agents.synapse import build_index
    data=Path(root)/'dashboard/data';path=data/'memory_graph.json'
    lock=runtime_lock_path(data/'synapse.lock');lock.parent.mkdir(parents=True,exist_ok=True)
    with lock.open('a+b') as handle:
        fcntl.flock(handle,fcntl.LOCK_EX)
        graph=json.loads(path.read_text()) if path.exists() else {'nodes':{},'edges':[]}
        nodes=graph['nodes'];edges=graph['edges'];now=datetime.datetime.now(datetime.timezone.utc).isoformat()
        reported='problem:KIN_SUBMIT_SELECTOR_HANG';solution='solution:CDP_FORCE_EVAL_CLICK'
        nodes.setdefault('memory:hub',{'type':'MemoryHub'})
        nodes.setdefault(reported,{'type':'ProblemPattern','pattern':'KIN_SUBMIT_SELECTOR_HANG','status':'reported_not_reproduced','resolvedCount':0,'concreteExamples':[]})
        nodes.setdefault(solution,{'type':'SolutionPattern','pattern':'CDP_FORCE_EVAL_CLICK','status':'guarded_implementation_tested','constraints':['exact approved editor','confirmed no owned answer','enabled button','durable before-submit intent','one click only','captcha never bypassed']})
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
                run=db.execute('SELECT slot_id FROM automation_slots WHERE question_id=? ORDER BY updated_at DESC LIMIT 1',(question_id,)).fetchone()
                run_id=run['slot_id'] if run else None
                kin._naver_pipeline_preflight_send(db,question_id,account,run_id=run_id)
                fresh=kin._naver_pipeline_article_snapshot(document['article']['url'],fallback_body=document['article'].get('body') if document['article'].get('scope')=='local_verified_publication' else None)
                if fresh['body_sha256']!=document['article']['body_sha256']:raise ValueError('Source changed; approved draft preserved')
                config=kin._naver_browser_account_config(account)
                with pipeline_lock(),kin._naver_browser_account_lock(account),sync_playwright() as playwright,kin._naver_browser_awake_browser(playwright,config) as browser:
                    pages=[p for c in browser.contexts for p in c.pages if 'kin.naver.com/qna/detail.naver' in p.url and kin.question_id(p.url)==question_id and p.locator('#answerRegisterButton').count()==1]
                    if len(pages)!=1:raise ValueError('Exactly one existing editor required; no new editor created')
                    page=pages[0]
                    response=page.context.request.get(document['question']['question_url'],timeout=15000)
                    if response.status!=200:raise ValueError('Current question ownership unavailable')
                    ownership=kin._naver_browser__parse_question_ownership(response.text(),account,question_id)
                    def before_submit():
                        nonlocal clicked
                        kin.begin_send(db,question_id,account,run_id=run_id);clicked=True
                    try:result=click_existing(page,document,ownership,before_submit)
                    except Exception:
                        if clicked:kin.finish_send(db,question_id,{'reason':'Repair submission uncertain; never repeat click'})
                        raise
                    kin.finish_send(db,question_id,result)
            row=db.execute('SELECT * FROM questions WHERE question_id=?',(question_id,)).fetchone()
        if not row['answer_id'] or not row['answer_url']:
            return {'ok':False,'status':'held','reason':'Submission outcome unknown; no repeat click','clicked':clicked}
        evidence=public_evidence(account,row,document)
        if evidence.get('verified') is True and row['state']!='published_verified':kin.record_verification(db,question_id,evidence)
        kin.snapshot(db)
        result={'ok':evidence.get('verified') is True,'status':'observed' if evidence.get('verified') is True else 'held',
                'account':account,'questionId':question_id,'publicUrl':evidence.get('answer_url') if evidence.get('verified') is True else None,
                'publicVerified':evidence.get('verified') is True,'clicked':clicked,'originalSendDay':row['send_day'],
                'reason':evidence.get('reason')}
        try:
            if remember(result):
                from common.crew_chat_bridge import emit_work_event
                emit_work_event(actor='patch',actor_label='패치',task_id='kin-repair:'+question_id,phase='completed',stage='recovery-verified',output_kind='지식iN 공개 답변·계정 확인 · '+('CDP 단일 클릭 복구' if clicked else '기존 답변 확인, 재등록 없음'))
        except (OSError,ValueError,KeyError):result['learningStatus']='pending; publication evidence preserved'
        return result
    except (ValueError,RuntimeError,OSError) as exc:
        return {'ok':False,'status':'held','reason':type(exc).__name__+': '+str(exc)[:300],'clicked':clicked}
    finally:db.close()
