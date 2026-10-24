import json
import sqlite3
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from common import kin_submit_repair as repair
from common.collection_observability import write


@pytest.fixture
def native(tmp_path,monkeypatch):
    monkeypatch.setattr(repair,'ROOT',tmp_path)
    db=sqlite3.connect(':memory:');db.row_factory=sqlite3.Row
    db.executescript('''CREATE TABLE questions(question_id,account,state,send_day,answer_id,answer_url,result);
    INSERT INTO questions VALUES('123','stone0747','drafted',NULL,NULL,NULL,NULL);
    CREATE TABLE automation_slots(slot_id,account,question_id,state,reason,updated_at);
    INSERT INTO automation_slots VALUES('old','stone0747','123','blocked','screen_failure','0');
    CREATE TABLE operating_cadence(id,last_completed_at,last_account,active_run_id,active_account,active_started_at);
    INSERT INTO operating_cadence VALUES(1,'previous','adinfo0905',NULL,NULL,NULL);''')
    @contextmanager
    def lock(path):yield True
    config=tmp_path/'config.json';config.write_text(json.dumps({'enabled':True}))
    state=tmp_path/'state.json';state.write_text('{}')
    def reserve(database,settings):
        with database:
            database.execute("INSERT INTO automation_slots VALUES('new','stone0747',NULL,'started',NULL,'1')")
            database.execute("UPDATE operating_cadence SET active_run_id='new',active_account='stone0747',active_started_at='now'")
        return {'state':'reserved','runId':'new','account':'stone0747'}
    def finish(database,run_id):
        with database:database.execute("UPDATE operating_cadence SET last_completed_at='new-completion',last_account=active_account,active_run_id=NULL,active_account=NULL,active_started_at=NULL")
    kin=SimpleNamespace(_naver_scheduler_file_lock=lock,_naver_scheduler_CONFIG=config,_naver_scheduler_STATE=state,
        _naver_scheduler_validate_config=Mock(),_naver_scheduler_cadence_status=Mock(return_value={'nextAccount':'stone0747'}),
        _naver_scheduler_now_kst=Mock(),_naver_scheduler_reserve_run=Mock(side_effect=reserve),
        _naver_pipeline_preflight_send=Mock(),_naver_pipeline_stamp=lambda:'now',
        _naver_pipeline_TERMINAL_SEND=('publishing','submitted_unverified','published_verified'),
        _naver_scheduler_complete_run=Mock(side_effect=finish),_naver_scheduler_write=write)
    yield db,kin
    db.close()


def test_prepared_editor_uses_native_reservation_and_durable_preflight(native):
    db,kin=native
    with repair.prepared_run(db,kin,'stone0747','123') as run:
        assert run=='new'
        assert db.execute("SELECT question_id FROM automation_slots WHERE slot_id='new'").fetchone()[0]=='123'
        kin._naver_pipeline_preflight_send.assert_called_once_with(db,'123','stone0747',run_id='new')
        with db:db.execute("UPDATE questions SET state='submitted_unverified',send_day='today'")
    kin._naver_scheduler_reserve_run.assert_called_once_with(db,{'enabled':True})  # No forced cadence or quota bypass.
    kin._naver_scheduler_complete_run.assert_called_once_with(db,'new')


def test_pre_submit_failure_preserves_previous_cadence_and_original_failure(native):
    db,kin=native;kin._naver_pipeline_preflight_send.side_effect=ValueError('quota held')
    with pytest.raises(ValueError,match='quota held'):
        with repair.prepared_run(db,kin,'stone0747','123'):pytest.fail('Must not reach UI submission')
    row=db.execute('SELECT * FROM operating_cadence').fetchone()
    assert row['last_completed_at']=='previous' and row['active_run_id'] is None
    assert db.execute("SELECT reason FROM automation_slots WHERE slot_id='old'").fetchone()[0]=='screen_failure'
    assert db.execute("SELECT state FROM automation_slots WHERE slot_id='new'").fetchone()[0]=='blocked'


@pytest.mark.parametrize('field,value',[('state','publishing'),('send_day','today'),('answer_id','15'),('answer_url','url'),('result','unknown')])
def test_uncertain_or_existing_submission_never_reserves_again(native,field,value):
    db,kin=native
    with db:db.execute(f'UPDATE questions SET {field}=?',(value,))
    with pytest.raises(ValueError,match='verification only'):
        with repair.prepared_run(db,kin,'stone0747','123'):pytest.fail('No repeat submission')
    kin._naver_scheduler_reserve_run.assert_not_called()


@pytest.mark.parametrize('screen_rejects',[False,True])
def test_registration_intent_is_committed_only_at_verified_screen_click(monkeypatch,screen_rejects):
    import naver_kin.posting as kin
    from common import kin_screen
    url='https://example.com/article';answer='승인 본문\n'+url
    document={'account':'stone0747','question':{'question_url':'https://kin.naver.com/qna/detail.naver?docId=487064308','title':'질문','body':'원문'},'answer_text':answer,'attribution':{'outboundUrl':url}}
    page=Mock();page.url=document['question']['question_url'];page.content.return_value='<div class="endTitleSection">질문</div>'
    page.locator.return_value.inner_text.return_value='원문'
    page.locator.return_value.count.return_value=1;page.locator.return_value.is_visible.return_value=True;page.locator.return_value.is_enabled.return_value=True
    page.locator.return_value.evaluate_all.return_value=[url]
    page.evaluate.return_value=[]
    monkeypatch.setattr(kin,'_naver_browser__check_service_state',Mock());monkeypatch.setattr(kin,'_naver_browser_wait_for_editor_ready',Mock())
    monkeypatch.setattr(kin_screen,'editor_paragraphs',lambda page:answer.splitlines())
    callbacks={};page.on.side_effect=lambda event,callback:callbacks.__setitem__(event,callback)
    gate=Mock()
    def click(*args,**kwargs):
        gate.assert_not_called()
        if screen_rejects:raise TimeoutError('screen decision failed')
        kwargs['before_click']()
        response=SimpleNamespace(url='https://kin.naver.com/ajax/detail/registerAnswerForSmartEditorOne.naver',request=SimpleNamespace(method='POST',post_data='docId=487064308'),status=200,json=lambda:{'isSuccess':True,'result':{'result':{'answerNo':15}}})
        callbacks['response'](response)
    monkeypatch.setattr(kin_screen,'visual_click',click)
    ownership={'known':True,'complete':True,'answer_ids':[]}
    if screen_rejects:
        with pytest.raises(TimeoutError):repair.click_existing(page,document,ownership,gate)
        gate.assert_not_called()
    else:
        result=repair.click_existing(page,document,ownership,gate)
        assert result['answer_id']=='15';gate.assert_called_once()
    assert page.remove_listener.call_count==2


@pytest.mark.parametrize('fails',[False,True])
def test_partial_ownership_inventory_preserves_editor_and_closes_only_owned_probe(fails):
    page=Mock();probe=page.context.new_page.return_value
    page.context.request.get.return_value.status=200
    kin=SimpleNamespace(_naver_browser__parse_question_ownership=Mock(return_value={'reason':'question_answers_partially_loaded','answer_ids':[]}),
                        _naver_browser__question_ownership=Mock(side_effect=ValueError('unavailable') if fails else None,return_value={'known':True,'complete':True,'answer_ids':[]}))
    if fails:
        with pytest.raises(ValueError):repair.current_ownership(page,kin,'stone0747','url','123')
    else:assert repair.current_ownership(page,kin,'stone0747','url','123')['complete']
    probe.close.assert_called_once();page.close.assert_not_called();page.goto.assert_not_called()


def test_unknown_submission_reconciliation_needs_positive_owner_and_exact_content():
    import naver_kin.posting as kin
    url='https://example.com/article';answer='승인된 본문입니다.\n'+url
    document={'question':{'question_url':'https://kin.naver.com/qna/detail.naver?docId=487064308'},'answer_text':answer,'attribution':{'outboundUrl':url}}
    script='''<script>naver.isLogin = true; var x={loginUserId:"stone0747"};
    window.oElementBaLogSender = new naver.kin.pc.detail.ElementBaLogSender({dirId:100,docId:487064308,totalAnswerCount:1,});</script>'''
    html=script+f'''<div class="endTitleSection">질문</div><div class="questionDetail">원문</div>
    <div class="answerArea _myAnswer" id="answer_16"><a id="optModify16"></a>
    <p class="se-text-paragraph">승인된 본문입니다.</p>
    <div class="se-component se-oglink"><a href="{url}"><strong class="se-oglink-title">참고 글</strong></a></div></div>'''
    result=repair.owned_answer_candidate(kin,html,'stone0747','487064308',document)
    assert result['answerId']=='16' and result['resubmitted'] is False
    assert repair.owned_answer_candidate(kin,html.replace('_myAnswer','other').replace('optModify16','other'),'stone0747','487064308',document) is None
    assert repair.owned_answer_candidate(kin,html.replace('승인된 본문입니다.','다른 본문'),'stone0747','487064308',document) is None
    assert repair.owned_answer_candidate(kin,html.replace(url,'https://different.example/'),'stone0747','487064308',document) is None
    with pytest.raises(kin._naver_browser_LoginRequiredError):repair.owned_answer_candidate(kin,html,'another_account','487064308',document)
