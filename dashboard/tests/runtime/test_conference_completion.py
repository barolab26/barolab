"""A queued meeting and an idle scheduler are never publication evidence."""
import json
from pathlib import Path
from unittest.mock import patch
import pytest
from common import conference_dispatch as conferences, project_autonomy as autonomy


@pytest.mark.parametrize('project,kind', [('naver_kin','kin'), ('threads','threads'), ('cf_blog','parameters'), ('naver_blog','parameters')])
def test_channel_cycle_waits_for_exact_conference_receipt(tmp_path, project, kind):
    config=tmp_path/'config.json';config.write_text(json.dumps({'enabled':True,'projects':[project]}))
    with patch.object(autonomy,'CONFIG',config), patch.object(conferences,'QUEUE',tmp_path/'queue'), \
         patch('server.agent_tools._ego_popen') as spawn:
        result=autonomy.run_project_cycle(project)
        assert result['status']=='awaiting_completion'
        assert not result['publicationVerified']
        assert autonomy.terminal_result(result) is None
        spawn.assert_not_called()
        path=conferences.QUEUE/(result['conferenceAgendaId']+'.json')
        row=json.loads(path.read_text());assert row['kind']==kind
        row.update(status='failed',errorType='RuntimeError',failureReason='model_timeout')
        path.write_text(json.dumps(row))
        terminal,_=autonomy.terminal_result(result)
        assert terminal['status']=='failed'
        assert terminal['reason']=='model_timeout'
        assert not terminal['publicationVerified']
        row.update(status='completed',outcomes=[],eligibility={'reason':'no_due_slot'})
        path.write_text(json.dumps(row))
        terminal,_=autonomy.terminal_result(result)
        assert terminal['status']=='no_work'
        assert terminal['eligibility']['reason']=='no_due_slot'
        assert not terminal['publicationVerified']
        row['requestedAt']+=1;path.write_text(json.dumps(row))
        terminal,_=autonomy.terminal_result(result)
        assert terminal['status']=='unknown'


def test_safe_cause_preserves_nested_model_timeout_without_secrets():
    cause=RuntimeError('AGY CLI 응답 시간 제한 초과.')
    wrapped=RuntimeError('Conference pending; retry the same agenda');wrapped.__cause__=cause
    assert conferences.conference_failure_reason(wrapped)=='model_timeout'
    assert conferences.conference_failure_reason(ValueError('secret input'))=='execution_error'
    assert conferences.conference_failure_reason(TimeoutError('Screen execution reached its turn budget'))=='screen_execution_budget_exhausted'
    wrapped=RuntimeError('Existing draft failed validation');wrapped.__context__=FileExistsError('private path')
    assert conferences.conference_failure_reason(wrapped)=='execution_evidence_directory_collision'


@pytest.fixture
def kin_failed_run(tmp_path,monkeypatch):
    import sqlite3
    monkeypatch.setattr(conferences,'ROOT',tmp_path)
    path=tmp_path/'dashboard/data/kin.sqlite3';path.parent.mkdir(parents=True)
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE automation_slots(slot_id,account,planned_at,state,question_id)')
        db.execute("INSERT INTO automation_slots VALUES('run-1','stone0747','2026-10-25T02:00:00+09:00','blocked','123')")
        db.execute('CREATE TABLE questions(question_id,account,state,send_day,answer_id,answer_url,result,created_at)')
        db.execute("INSERT INTO questions VALUES('123','stone0747','drafted',NULL,NULL,NULL,NULL,'2026-10-25')")
    return path,{'arguments':{'account':'stone0747','date':'2026-10-25'},'eligibility':{'runs':[{'runId':'run-1','state':'blocked'}]}}


def test_kin_retry_binds_original_unsubmitted_question_without_changing_ledger(kin_failed_run):
    path,row=kin_failed_run;before=path.read_bytes()
    assert conferences.kin_retry_target(row)=={'runId':'run-1','account':'stone0747','questionId':'123'}
    assert path.read_bytes()==before
    row['arguments']['account']='adinfo0905'
    with pytest.raises(ValueError,match='does not match'):conferences.kin_retry_target(row)


@pytest.mark.parametrize('field,value',[('state','publishing'),('send_day','2026-10-25'),('answer_id','15'),('answer_url','https://kin.naver.com/answer'),('result','uncertain')])
def test_kin_retry_rejects_every_submission_marker(kin_failed_run,field,value):
    import sqlite3
    path,row=kin_failed_run
    with sqlite3.connect(path) as db:db.execute(f'UPDATE questions SET {field}=?',(value,))
    with pytest.raises(ValueError,match='no retry'):conferences.kin_retry_target(row)


def test_kin_retry_cannot_follow_another_latest_draft(kin_failed_run):
    import sqlite3
    path,row=kin_failed_run
    with sqlite3.connect(path) as db:db.execute("INSERT INTO questions VALUES('456','stone0747','drafted',NULL,NULL,NULL,NULL,'2026-10-26')")
    with pytest.raises(ValueError,match='no retry'):conferences.kin_retry_target(row)


def test_kin_worker_rechecks_submission_and_cannot_switch_questions(kin_failed_run,monkeypatch):
    import sqlite3
    from unittest.mock import Mock
    import naver_kin.posting as engine
    path,row=kin_failed_run
    row['retryTarget']=conferences.kin_retry_target(row)
    for name in ('_naver_scheduler_reserve_run','_naver_authoring_generate_for_slot','_naver_browser_publish','_naver_browser_verify_public'):
        monkeypatch.setattr(engine,name,Mock())
    for name in ('_conference_retry','_conference_results','_conference_failures'):
        monkeypatch.setattr(engine,name,None,raising=False)
    reserve=engine._naver_scheduler_reserve_run
    conferences.install_channel_conferences('kin');engine._conference_retry=row
    with sqlite3.connect(path) as db:db.execute("UPDATE questions SET state='submitted_unverified'")
    with pytest.raises(ValueError,match='no retry'):engine._naver_scheduler_reserve_run(None,{})
    reserve.assert_not_called()
    with pytest.raises(ValueError,match='Different question'):
        engine._naver_browser_publish('stone0747','https://kin.naver.com/qna/detail.naver?docId=487064309','answer')
    with pytest.raises(ValueError,match='replacement question'):
        engine._naver_authoring_generate_for_slot('stone0747','new-run','test-model')


def test_unverified_conference_outcome_is_not_success(tmp_path):
    identity='a'*64
    row={'agendaId':identity,'kind':'threads','requestedAt':10,'status':'completed','outcomes':[{'outcome':'게시 확인 중','publicationVerified':False}]}
    (tmp_path/(identity+'.json')).write_text(json.dumps(row))
    with patch.object(conferences,'QUEUE',tmp_path):
        terminal,_=autonomy.terminal_result({'conferenceAgendaId':identity,'conferenceRequestedAt':10,'project':'threads'})
    assert terminal['status']=='unknown' and terminal['ok'] is False
    assert terminal['publicationVerified'] is False


def test_independent_channel_can_run_while_blog_preparation_is_active(tmp_path):
    import os
    pid=os.getpid();ticks=Path('/proc',str(pid),'stat').read_text().split(') ',1)[1].split()[19]
    for name,row in {
        'a':{'status':'running','kind':'parameters','pid':pid,'startTicks':ticks},
        'b':{'status':'queued','kind':'parameters','requestedAt':1},
        'c':{'status':'queued','kind':'threads','requestedAt':2},
        'd':{'status':'queued','kind':'threads','requestedAt':3},
        'e':{'status':'queued','kind':'kin','requestedAt':4},
    }.items():
        (tmp_path/(name*64+'.json')).write_text(json.dumps(row))
    with patch.object(conferences,'QUEUE',tmp_path), patch.object(conferences.subprocess,'Popen') as spawn:
        spawn.return_value.pid=pid
        assert conferences.process_once() is True
        assert spawn.call_args.args[0][-1]=='c'*64
        assert conferences.process_once() is True
        assert spawn.call_args.args[0][-1]=='e'*64
        assert conferences.process_once() is False
        assert spawn.call_count==2
