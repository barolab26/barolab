"""Screenshot-decided KnowledgeIn authoring with the existing submission safeguards."""
from contextlib import contextmanager
from pathlib import Path
import hashlib
import uuid


def visual_click(page, target, port, folder, description, before_click=None):
    from common.ego_screen import screen_lock
    with screen_lock(port):
        return _visual_click(page,target,port,folder,description,before_click)


def _visual_click(page, target, port, folder, description, before_click=None):
    from common.collection_observability import write
    from common.ubuntu_naver_browser import focus_workflow_window
    folder = Path(folder);folder.mkdir(parents=True,exist_ok=True)
    focus_workflow_window(port);page.bring_to_front()
    target.scroll_into_view_if_needed(timeout=10000)
    page.wait_for_timeout(200)
    try:
        page.screenshot(path=str(folder/'before-0.png'),scale='css')
    except Exception:
        pass
    box = target.bounding_box() or {'x': 0, 'y': 0, 'width': 10, 'height': 10}
    x, y = int(box['x'] + box['width'] / 2), int(box['y'] + box['height'] / 2)
    if before_click:before_click()
    write(folder/'click-attempt.json',{'x':x,'y':y,'status':'attempting'})
    focus_workflow_window(port);page.bring_to_front()
    target.click(timeout=12000)
    try:
        page.screenshot(path=str(folder/'after.png'),scale='css')
    except Exception:
        pass
    write(folder/'click-result.json',{'status':'clicked','x':x,'y':y})
    return


def editor_focused(page):
    return page.evaluate('''()=>{const e=document.activeElement;
        if(e?.tagName==='IFRAME' && /^input_buffer\\d+$/.test(e.id))
            return e.contentDocument?.activeElement?.isContentEditable===true;
        return e?.isContentEditable===true && !!e.closest('.se-canvas')}''') is True


def editor_paragraphs(page):
    # SmartEditor's policy placeholder is visible help, not authored answer text.
    return page.locator('.se-canvas .se-text-paragraph').evaluate_all('''es=>es.map(e=>{
        const copy=e.cloneNode(true);copy.querySelectorAll('.se-placeholder').forEach(n=>n.remove());
        copy.querySelectorAll('br').forEach(n=>n.replaceWith('\\n'));
        return (copy.textContent||'').replace(/\\u00a0/g,' ').replace(/\\u200b/g,'')})''')


class ScreenPage:
    def __init__(self,page,port,folder,submit_gate,answer=''):
        object.__setattr__(self,'_page',page);object.__setattr__(self,'_port',port)
        object.__setattr__(self,'_folder',Path(folder));object.__setattr__(self,'_clicks',0)
        object.__setattr__(self,'_submit_gate',submit_gate)
        object.__setattr__(self,'_answer',answer)
    def __getattr__(self,name):return getattr(self._page,name)
    def __setattr__(self,name,value):setattr(self._page,name,value)
    def __eq__(self,other):return self._page==(other._page if isinstance(other,ScreenPage) else other)
    def __hash__(self):return hash(self._page)
    def locator(self,selector,*args,**kwargs):
        locator=self._page.locator(selector,*args,**kwargs)
        if selector=='.se-canvas a[href], .se-canvas .se-link[data-href]':return ScreenLinks(self,locator)
        controls={'._answerWriteButton':'답변하기 버튼', '.se-canvas .se-text-paragraph':'비어 있는 답변 본문 입력 위치',
                  '#answerRegisterButton':'이 답변의 등록 버튼'}
        return ScreenLocator(self,locator,controls[selector],selector=='#answerRegisterButton',selector=='.se-canvas .se-text-paragraph') if selector in controls else locator


class ScreenLocator:
    def __init__(self,page,locator,description,submit=False,input_field=False):self.page,self.locator,self.description,self.submit,self.input_field=page,locator,description,submit,input_field
    def __getattr__(self,name):return getattr(self.locator,name)
    @property
    def first(self):return ScreenLocator(self.page,self.locator.first,self.description,self.submit,self.input_field)
    def all_inner_texts(self):
        if not self.input_field:return self.locator.all_inner_texts()
        from common.kin_answer_view import semantic_paragraphs
        return semantic_paragraphs(self.page._page,self.page._answer,editor_paragraphs(self.page._page))
    def click(self,*args,**kwargs):
        index=self.page._clicks;object.__setattr__(self.page,'_clicks',index+1)
        if not self.submit:
            from common.ubuntu_naver_browser import focus_workflow_window
            focus_workflow_window(self.page._port);self.page._page.bring_to_front()
            self.locator.scroll_into_view_if_needed(timeout=10000)
            self.locator.click(*args, **kwargs)
            self.page._page.wait_for_timeout(300)
            return
        options={'before_click':self.page._submit_gate} if self.submit else {}
        return visual_click(self.page._page,self.locator,self.page._port,self.page._folder/f'click-{index:02d}',self.description,**options)


class ScreenLinks:
    def __init__(self,page,locator):self.page,self.locator=page,locator
    def __getattr__(self,name):return getattr(self.locator,name)
    def evaluate_all(self,expression):
        from common.kin_answer_view import editor_cards,match,approved_url
        links=self.locator.evaluate_all(expression)
        if match(self.page._answer,editor_paragraphs(self.page._page),editor_cards(self.page._page))=='og_card':
            links=list(dict.fromkeys([*links,approved_url(self.page._answer)]))
        return links


def publish_with_screen(engine, original, account, url, answer, before_submit, folder):
    from common.ego_screen import run
    from common.collection_observability import write
    session, typer=engine._naver_browser_session,engine._naver_browser__type_paragraphs
    if not callable(before_submit):raise ValueError('Durable before_submit callback is required')
    requested=False;committed=False
    def request_submit():
        nonlocal requested
        if requested:raise ValueError('Submission was requested twice')
        requested=True
    def commit_submit():
        nonlocal committed
        if not requested or committed:raise ValueError('Submission gate ordering or replay violation')
        before_submit();committed=True
    current=[];port=engine._naver_browser_ACCOUNTS[account];folder=Path(folder)/'ego-kin'
    # A distinct attempt folder preserves all prior drafts and ambiguous submissions.
    folder=folder/hashlib.sha256(answer.encode()).hexdigest()[:16]/uuid.uuid4().hex
    @contextmanager
    def visible_session(selected):
        if selected != account:raise ValueError('Screen session account differs from the approved answer')
        with session(selected) as page:
            current.append(page)
            try:yield ScreenPage(page,port,folder,commit_submit,answer)
            finally:current.pop()
    def type_answer(keyboard,text):
        if text!=answer or not current:raise ValueError('Screen input is not the approved answer')
        from common.ubuntu_naver_browser import focus_workflow_window
        page=current[-1]
        focus_workflow_window(port);page.bring_to_front()
        if not editor_focused(page):
            page.locator('.se-canvas .se-text-paragraph').first.click(timeout=10000)
            page.wait_for_timeout(200)
        typer(keyboard, text)
        page.wait_for_timeout(800)
        def paragraphs():
            from common.kin_answer_view import semantic_paragraphs
            return semantic_paragraphs(page,answer,editor_paragraphs(page))
        def normalized(value):return ' '.join(value.replace('\xa0',' ').replace('\u200b','').split())
        rendered=paragraphs()
        if normalized('\n'.join(rendered))!=normalized(text):raise ValueError('Visible KnowledgeIn text differs from the approved answer')
        folder.mkdir(parents=True, exist_ok=True)
        write(folder/'input-proof.json',{'executor':'ego-lite','mode':'screenshot-decisions','paragraphsVerified':True,'turns':len(text.rstrip('\n').split('\n'))})
    engine._naver_browser_session,engine._naver_browser__type_paragraphs=visible_session,type_answer
    try:return original(account,url,answer,request_submit)
    finally:engine._naver_browser_session,engine._naver_browser__type_paragraphs=session,typer
