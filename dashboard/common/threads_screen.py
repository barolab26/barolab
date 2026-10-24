"""Threads screen submission and bounded read-only reconciliation for conference workers."""
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from pathlib import Path
import hashlib
import json
import re
import time

PORT = 9450
ACCOUNT = 'mustpickinfo'


def recover_unknown(engine, config, part):
    """Replies belong to the parent's conversation, not the account's main feed."""
    empty = {'matched': False, 'reason': 'recovery_unverified'}
    text = part.get('text');intent = engine._threads_adapter__published_time(part.get('intent_at'))
    if part.get('account_key') != ACCOUNT or not isinstance(text,str) or not intent:
        return {**empty,'reason':'recovery_identity_or_intent_missing'}
    if hashlib.sha256(text.encode()).hexdigest()!=part.get('text_sha256'):
        return {**empty,'reason':'recovery_ledger_text_mismatch'}
    outbound=part.get('outbound_url')
    if outbound:
        from urllib.parse import urlsplit,parse_qs
        u=urlsplit(outbound);q=parse_qs(u.query)
        if u.scheme!='https' or text.count(outbound)!=1 or any(q.get(k)!=[v] for k,v in [('utm_source','threads'),('utm_medium','social'),('utm_campaign','cf_bridge')]) or len(q.get('utm_content',[]))!=1 or not q['utm_content'][0]:
            return {**empty,'reason':'recovery_unique_utm_required'}
    reply=part.get('kind')=='followup';parent=str(part.get('parent_platform_id') or '')
    if reply and not re.fullmatch(r'\d+',parent):return {**empty,'reason':'recovery_parent_required'}
    try:
        import requests
        client=engine._threads_adapter_Client(config);engine._threads_adapter__identity(client)
        matches={};after=None;seen=set();complete=False;read=0
        for _ in range(2):
            params={'fields':'id,text,username,permalink,timestamp,is_reply,replied_to','limit':25}
            if after:params['after']=after
            if reply:
                # Only this validated read endpoint extends the frozen client's allowlist.
                response=requests.get(client.base+'/'+parent+'/conversation',params=params,
                    headers={'Authorization':'Bearer '+client.token},timeout=20,allow_redirects=False,verify=True)
                if response.status_code!=200:return {**empty,'reason':'recovery_conversation_unavailable'}
                report=response.json()
            else:
                params['since']=int(datetime.fromisoformat(intent).timestamp())
                report=client.request('GET','me/threads',params)
            rows=report.get('data');paging=report.get('paging',{})
            if not isinstance(rows,list) or len(rows)>25 or not isinstance(paging,dict):return empty
            read+=len(rows)
            for row in rows:
                if not isinstance(row,dict):return empty
                published=engine._threads_adapter__published_time(row.get('timestamp'));pid=str(row.get('id',''))
                if row.get('username')!=ACCOUNT or row.get('text')!=text or not published or datetime.fromisoformat(published)<datetime.fromisoformat(intent):continue
                if datetime.fromisoformat(published)>datetime.now(timezone.utc):continue
                if row.get('is_reply') is not reply:continue
                if reply and str((row.get('replied_to') or {}).get('id'))!=parent:continue
                if not re.fullmatch(r'\d+',pid) or not engine._threads_adapter__permalink(row.get('permalink')):continue
                matches[pid]={'platform_id':pid,'permalink':row['permalink'],'published_at':published}
            if not paging.get('next'):complete=True;break
            cursors=paging.get('cursors') or {};after=cursors.get('after') if isinstance(cursors,dict) else None
            if not isinstance(after,str) or not re.fullmatch(r'[A-Za-z0-9_=-]{1,2048}',after) or after in seen:break
            seen.add(after)
        if not complete:return {**empty,'reason':'recovery_inventory_incomplete'}
        if len(matches)!=1:return {**empty,'reason':'recovery_ambiguous_matches' if matches else 'recovery_no_match'}
        return {**next(iter(matches.values())),'matched':True,'match_count':1,'account_key':ACCOUNT,
            'text_sha256':part['text_sha256'],'outbound_url':outbound,'reason':None,
            'evidence':{'inventory_complete':True,'returned_posts':read,'account_verified':True,
                'exact_text_equal':True,'after_intent':True,'parent_verified':reply,'read_only':True}}
    except (engine._threads_adapter_AdapterError,requests.RequestException,ValueError,TypeError,AttributeError):
        return empty


@contextmanager
def session(for_submission=False):
    from playwright.sync_api import sync_playwright
    from common.browser_session import connect_sync
    from common.ubuntu_naver_browser import account_paths,focus_workflow_window
    exe,profile,_=account_paths(PORT)
    with sync_playwright() as playwright:
        browser=connect_sync(playwright,f'http://127.0.0.1:{PORT}',exe,profile,log=lambda _:None)
        pages=[p for c in browser.contexts for p in c.pages if re.match(r'https://(?:www\.)?threads\.(?:com|net)/',p.url)]
        if not pages:raise RuntimeError('threads_existing_tab_required')
        page=pages[0]
        if for_submission:
            pending=set()
            root=Path(__file__).resolve().parents[2]/'threads_posting/output/scheduled'
            for proof in root.glob('*/*/ego-*/intent.json'):
                if not proof.with_name('readback.json').exists():
                    try:
                        import sqlite3
                        evidence=json.loads(proof.read_text())
                        database=Path(__file__).resolve().parents[1]/'data/threads.sqlite3'
                        with sqlite3.connect(database.resolve().as_uri()+'?mode=ro',uri=True) as db:
                            adopted=db.execute("SELECT 1 FROM parts WHERE part_id=? AND state IN ('api_submitted','published_verified') AND platform_id IS NOT NULL",(evidence['partId'],)).fetchone()
                        if not adopted:pending.add(evidence['targetId'])
                    except (OSError,ValueError,KeyError,sqlite3.Error):raise RuntimeError('threads_submission_evidence_unreadable')
            cdp=page.context.new_cdp_session(page)
            try:target_id=cdp.send('Target.getTargetInfo')['targetInfo']['targetId']
            finally:cdp.detach()
            if target_id in pending:raise RuntimeError('threads_uncertain_submission_tab_preserved')
        focus_workflow_window(PORT);page.bring_to_front()
        # Disconnecting Playwright preserves the existing browser and every user tab.
        yield page


def web_identity(page):
    # Only the navigation Profile control identifies the signed-in account.
    return page.locator('a').evaluate_all('''els=>els.some(e=>{
      const label=(e.getAttribute('aria-label')||e.querySelector('svg[aria-label]')?.getAttribute('aria-label')||e.querySelector('svg title')?.textContent||e.innerText||'').trim();
      return /^(Profile|프로필)$/.test(label)&&/^\\/@mustpickinfo\\/?$/.test(e.getAttribute('href')||'')})''') is True


def verify_reply_context(page,dialog,parent):
    from urllib.parse import urlsplit
    if (urlsplit(page.url).path.rstrip('/')!=urlsplit(parent['permalink']).path.rstrip('/')
            or dialog.get_by_text('New thread',exact=True).count()
            or not dialog.get_by_text(re.compile(r'^(Reply|답글)$')).count()
            or ' '.join(parent['text'].split()) not in ' '.join(dialog.inner_text().split())):
        raise ValueError('threads_visible_reply_parent_unverified')


def composer(page):
    """Threads also renders composers without an ARIA dialog role."""
    editor=page.locator('[contenteditable="true"]:visible')
    if editor.count()!=1:raise ValueError('threads_unique_editor_required')
    node=editor
    for _ in range(14):
        node=node.locator('..')
        if node.count()!=1 or node.evaluate('e=>e.tagName') in ('BODY','HTML'):
            break
        heading=node.get_by_text(re.compile(r'^(New thread|새 스레드|스레드 만들기|Reply|답글)$'),exact=True)
        submit=node.get_by_role('button',name=re.compile(r'^(Post|Reply|게시|답글)$'))
        if heading.count()>0 and submit.count()==1:return node
    raise ValueError('threads_composer_not_ready')


def owned_empty_composer(page,folder):
    """Resume an empty composer opened by this exact part, before any submit intent."""
    try:
        if composer(page).locator('[contenteditable="true"]').inner_text().strip():return None
    except ValueError:return None
    cdp=page.context.new_cdp_session(page)
    try:target=cdp.send('Target.getTargetInfo')['targetInfo']['targetId']
    finally:cdp.detach()
    for proof in sorted(Path(folder).glob('ego-[0-9]*/open/screen-execution.json'),reverse=True):
        state=json.loads(proof.read_text())
        if (state.get('editorTargetId')==target and state.get('port')==PORT
                and state.get('status') in ('held','screen_task_complete') and state.get('turns')
                and state.get('written')==[] and not (proof.parent.parent/'intent.json').exists()):
            return str(proof)
    return None


def existing_draft(page):
    """A default empty inline reply box is not a user draft."""
    protected = page.locator('[contenteditable="true"]').evaluate_all("""els=>els.some(e=>
        (e.innerText||'').trim().length>0 ||
        (e.getClientRects().length>0 && !!e.closest('[role="dialog"]')))""") is True
    if protected:return True
    try:
        composer(page)
        return True
    except ValueError:return False


def completed_draft(page,part,folder):
    """Resume only this task's fully typed, never-submitted browser draft."""
    editors=page.locator('[role="dialog"] [contenteditable="true"]')
    if editors.count()!=1:
        try:editors=composer(page).locator('[contenteditable="true"]')
        except ValueError:return None
    if editors.count()!=1 or editors.inner_text().rstrip('\n')!=part['text'].rstrip('\n'):return None
    cdp=page.context.new_cdp_session(page)
    try:target=cdp.send('Target.getTargetInfo')['targetInfo']['targetId']
    finally:cdp.detach()
    refs=[str(i) for i in range(len(part['text'].split('\n')))]
    for proof in sorted(Path(folder).glob('ego-[0-9]*/type/screen-execution.json'),reverse=True):
        state=json.loads(proof.read_text())
        if (state.get('status')=='screen_task_complete' and state.get('editorTargetId')==target
                and state.get('written')==refs and not (proof.parent.parent/'intent.json').exists()):
            return str(proof)
    return None


class ScreenAdapter:
    def __init__(self,engine):self.engine=engine
    def connection_status(self,config):return self.engine._threads_adapter_connection_status(config)
    def readiness_status(self,config):
        result=self.engine._threads_adapter_readiness_status(config)
        try:
            with session() as page:logged_in=web_identity(page)
        except Exception:logged_in=False
        result['webAccountVerified']=logged_in;result['executor']='ego-lite'
        if not logged_in:result.update(publishReady=False,ready=False,reason='threads_web_login_required')
        return result
    def verify_public(self,*args):return self.engine._threads_adapter_verify_public(*args)
    def recover_unknown(self,config,part):return recover_unknown(self.engine,config,part)
    def submit_part(self,config,part,before_submit):
        from common.ego_screen import run
        from common.kin_screen import visual_click
        from common.collection_observability import write
        if config['account_key']!=ACCOUNT or part['account_key']!=ACCOUNT:raise ValueError('threads_account_mismatch')
        folder=Path(self.engine.BASE_DIR)/'output'/'scheduled'/part['publication_date']/part['part_id']/('ego-'+str(time.time_ns()))
        folder.mkdir(parents=True)
        parent=None
        if part['kind']=='followup':
            client=self.engine._threads_adapter_Client(config);self.engine._threads_adapter__identity(client)
            parent=client.request('GET',str(part['parent_platform_id']),{'fields':'id,username,permalink,text'})
            if (str(parent.get('id'))!=str(part['parent_platform_id']) or parent.get('username')!=ACCOUNT
                    or not self.engine._threads_adapter__permalink(parent.get('permalink')) or not parent.get('text')):
                raise ValueError('threads_parent_identity_unverified')
        with session(for_submission=True) as page:
            if not web_identity(page):raise RuntimeError('threads_web_login_required')
            protected=existing_draft(page)
            resume=completed_draft(page,part,folder.parent) if protected else None
            opened_before=owned_empty_composer(page,folder.parent) if protected and not resume else None
            if protected and not resume and not opened_before:raise RuntimeError('threads_existing_draft_preserved')
            if not resume and not opened_before:
                target='https://www.threads.com/@'+ACCOUNT
                if parent:target=parent['permalink']
                def opened():
                    composer(page)
                run(page,port=PORT,folder=folder/'open',urls={'approved-thread':target},max_turns=10,time_budget_seconds=180,
                    goal='Threads에서 approved-thread로 이동하고 '+('이 글에 답글을 작성하는 입력창' if part['kind']=='followup' else '새 게시물 작성창')+
                        '을 연다. 아직 글을 입력하거나 게시하지 않는다. 입력창이 보이면 완료한다.',completion_check=opened)
            dialog=composer(page);editor=dialog.locator('[contenteditable="true"]')
            if parent:verify_reply_context(page,dialog,parent)
            lines=part['text'].split('\n');refs=[{'ref':str(i),'kind':'write','text':line} for i,line in enumerate(lines)]
            def check(written):
                expected='\n'.join(lines[:len(written)])
                return '' if editor.inner_text().rstrip('\n')==expected.rstrip('\n') else '입력 본문이 승인 원고와 다릅니다. 추가 입력 전에 화면을 보고 고치세요.'
            def composed():
                if editor.inner_text().rstrip('\n')!=part['text'].rstrip('\n'):raise ValueError('threads_visible_text_mismatch')
            if not resume:
                run(page,port=PORT,folder=folder/'type',references=refs,max_turns=22,time_budget_seconds=480,
                    goal='승인된 Threads 원고를 각 ref 순서대로 직접 타이핑한다. write는 한 줄을 입력하고 Enter를 한 번 누른다. 빈 줄도 유지한다. 붙여넣기와 게시 버튼은 사용하지 않는다. 모든 글과 문단을 눈으로 확인한 뒤 완료한다.',input_check=check,completion_check=composed)
            else:
                composed();write(folder/'resumed-draft.json',{'proof':resume,'textVerified':True})
            button=dialog.get_by_role('button',name=re.compile(r'^(Post|Reply|게시|답글)$'))
            if button.count()!=1:raise ValueError('threads_exact_submit_control_required')
            intent={}
            def commit():
                composed()
                if parent:verify_reply_context(page,dialog,parent)
                if not web_identity(page):raise ValueError('threads_account_changed')
                before_submit();intent['at']=datetime.now(timezone.utc).isoformat()
                cdp=page.context.new_cdp_session(page)
                try:target_id=cdp.send('Target.getTargetInfo')['targetInfo']['targetId']
                finally:cdp.detach()
                write(folder/'intent.json',{'partId':part['part_id'],'intentAt':intent['at'],'executor':'ego-lite','targetId':target_id})
                # API timestamps have whole-second precision; the click must follow the durable intent's second.
                page.wait_for_timeout(1100)
            visual_click(page,button,PORT,folder/'submit','현재 원고의 '+('답글' if part['kind']=='followup' else '게시')+' 버튼',before_click=commit)
            for delay in (2,5,10):
                page.wait_for_timeout(delay*1000)
                found=self.recover_unknown(config,{**part,'intent_at':intent['at']})
                if found.get('matched'):
                    write(folder/'readback.json',found)
                    return found
            raise RuntimeError('threads_screen_submit_outcome_unknown')


def repair_claims(engine,config,db_path,now):
    """Called with the existing scheduler lock: preserve abandoned claim evidence."""
    with engine._threads_pipeline_connect(db_path) as db:
        rows=db.execute("SELECT * FROM authoring_slots WHERE account_key=? AND state='claimed'",(config['account_key'],)).fetchall()
        for raw in rows:
            row=dict(raw)
            try:age=now-datetime.fromisoformat(row['updated_at'].replace('Z','+00:00'))
            except (ValueError,TypeError,AttributeError):continue
            if age<timedelta(minutes=30):continue
            if db.execute('SELECT 1 FROM parts WHERE account_key=? AND publication_date=? AND slot=?',(row['account_key'],row['day'],row['slot'])).fetchone():continue
            key='abandoned_authoring_claim:'+row['account_key']+':'+row['day']+':'+row['slot']
            db.execute('INSERT OR REPLACE INTO runtime VALUES(?,?)',(key,json.dumps({'claim':row,'recoveredAt':now.isoformat(),'reason':'scheduler_lock_owned_no_parts'})))
            db.execute("DELETE FROM authoring_slots WHERE account_key=? AND day=? AND slot=? AND state='claimed' AND updated_at=?",(row['account_key'],row['day'],row['slot'],row['updated_at']))


def install(engine):
    engine._namespace_adapter=ScreenAdapter(engine)
    tick=engine._threads_scheduler_tick;slot=engine._threads_scheduler_current_slot
    active_path=[engine._threads_config_DB]
    def current_slot(config,now,used_slots=()):
        if not used_slots:
            day=now.astimezone(engine._threads_pipeline_KST).date().isoformat();hm=now.astimezone(engine._threads_pipeline_KST).strftime('%H:%M')
            with engine._threads_pipeline_connect(active_path[0]) as db:
                row=db.execute("SELECT min(slot) FROM parts WHERE account_key=? AND publication_date=? AND slot<=? AND state='queued' AND kind='main'",(config['account_key'],day,hm)).fetchone()
            if row and row[0]:return row[0]
        return slot(config,now,used_slots)
    def scheduler_tick(config_path=engine._threads_config_CONFIG,db_path=engine._threads_config_DB,output=engine._threads_config_PUBLIC):
        active_path[0]=db_path
        with engine._threads_scheduler_lock():
            repair_claims(engine,engine._threads_config_load(config_path),db_path,datetime.now(timezone.utc))
        return tick(config_path,db_path,output)
    engine._threads_scheduler_current_slot=current_slot;engine._threads_scheduler_tick=scheduler_tick
