import hashlib
import json
from pathlib import Path
from unittest.mock import Mock
import pytest
from common import repair_workflow as repair
from common.collection_observability import write,load


@pytest.fixture
def held(tmp_path,monkeypatch):
    monkeypatch.setattr(repair,'ROOT',tmp_path)
    row={'type':'project_recovery_v1','taskId':'same-work','plan':{},'planSha256':hashlib.sha256(b'{}').hexdigest(),
         'status':'held','step':'classify','steps':{'classify:2':{'startedAt':1}},'classificationRound':2,
         'resumeAttempted':False,'discovered':{'fileHashes':{'source.py':'old'}},
         'classification':{'kind':'inspect','inspectRole':'patch'},'inspection':{'diagnosis':'Old runtime evidence'}}
    path=tmp_path/'plan.json';write(path,row)
    discover=Mock(return_value={'fileHashes':{'source.py':'new'},'environment':{'browserWindow':{'status':'observed'}}})
    monkeypatch.setattr(repair,'_discover_recovery',discover)
    return path,row,discover


def test_held_readonly_phase_rechecks_new_evidence_without_business_replay(held):
    path,row,discover=held
    assert repair.dispatch_project_recovery_once()
    saved=load(path)
    assert saved['status']=='ready' and saved['step']=='classify' and saved['classificationRound']==3
    assert saved['planSha256']==row['planSha256'] and saved['plan']==row['plan']
    assert saved['steps']==row['steps'] and saved['resumeAttempted'] is False
    assert saved['evidenceHistory'][0]['inspection']==row['inspection']
    assert 'inspection' not in saved


def test_unchanged_held_work_is_polled_without_new_model_or_phase(held):
    path,row,discover=held
    discover.return_value=row['discovered']
    assert repair.dispatch_project_recovery_once() is False
    assert load(path)['status']=='held' and load(path)['classificationRound']==2
    assert repair.dispatch_project_recovery_once() is False
    discover.assert_called_once()


@pytest.mark.parametrize('step',['apply','resume','verify'])
def test_business_and_code_mutations_are_never_replayed_from_held(held,step):
    path,row,discover=held;row['step']=step;write(path,row)
    assert repair.dispatch_project_recovery_once() is False
    discover.assert_not_called()


def test_transient_readonly_retry_has_a_finite_budget(held):
    path,row,discover=held;discover.return_value=row['discovered']
    for expected in (1,2):
        row=load(path);row.update(status='held',errorCode='classify:RuntimeError',evidenceRecheckAt=0);write(path,row)
        assert repair.dispatch_project_recovery_once()
        assert load(path)['readonlyRetries']==expected
    row=load(path);row.update(status='held',errorCode='classify:RuntimeError',evidenceRecheckAt=0);write(path,row)
    assert repair.dispatch_project_recovery_once() is False
    assert load(path)['readonlyRetries']==2 and load(path)['resumeAttempted'] is False


@pytest.mark.parametrize('eligible,guard_allows,expected',[(False,True,'held'),(True,False,'held'),(True,True,'ready')])
def test_runtime_retry_needs_host_eligibility_and_original_submission_guard(held,monkeypatch,eligible,guard_allows,expected):
    path,row,discover=held
    # Use the normal immutable recovery identity; only the read-only classifier is mocked.
    canonical=repair._recovery_path(row['taskId']);row.update(status='ready',classificationRound=3,discovered={'originalRetryEligible':eligible});write(canonical,row);path.unlink()
    monkeypatch.setattr(repair,'_classify_recovery',lambda *args:{'kind':'retry_original'})
    guard=Mock(side_effect=None if guard_allows else ValueError('Submission uncertain'))
    monkeypatch.setattr(repair,'_recovery_resume_guard',guard)
    result=repair.advance_project_recovery(row['taskId'],row['planSha256'],actor='jarvis')
    saved=load(canonical)
    assert saved['status']==expected and saved['resumeAttempted'] is False
    if expected=='ready':assert saved['step']=='resume'
    else:assert result['ok'] is False


def test_source_discovery_finds_existing_regression_in_canonical_test_directory(tmp_path,monkeypatch):
    from common import coding_job,recovery_evidence
    name='dashboard/common/window_helper.py';source=tmp_path/name;source.parent.mkdir(parents=True);source.write_text('def work(): return 1\n')
    test=tmp_path/'dashboard/tests/common/test_window_helper.py';test.parent.mkdir(parents=True);test.write_text('from common import window_helper\ndef test_work(): assert window_helper.work()==1\n')
    monkeypatch.setattr(coding_job,'derive_coding_scope',lambda *args:[name])
    monkeypatch.setattr(coding_job,'derive_edit_regions',lambda *args,**kwargs:{})
    monkeypatch.setattr(recovery_evidence,'error_source_frames',lambda *args:[])
    monkeypatch.setattr(recovery_evidence,'environment_evidence',lambda *args:{})
    monkeypatch.setattr(recovery_evidence,'PROJECT_SOURCES',{})
    result=repair._discover_recovery({'plan':{'projectRoot':str(tmp_path),'project':'naver_blog','sourceSnapshot':{'lastError':'Window unavailable'},'action':{'tool':'run_project_cycle'}}})
    assert result['testFiles']==['dashboard/tests/common/test_window_helper.py']


def test_dashboard_common_patch_preserves_all_registered_channel_mutation_locks(tmp_path,monkeypatch):
    from contextlib import contextmanager
    import dashboard.metrics as metrics
    (tmp_path/'dashboard/data').mkdir(parents=True);write(tmp_path/'dashboard/data/threads-automation.json',{'account_key':'registered_account'})
    observed=[]
    @contextmanager
    def lock(path):observed.append(str(path));yield True
    monkeypatch.setattr(metrics,'collector_lock',lock)
    row={'plan':{'projectRoot':str(tmp_path),'project':'naver_blog'},'discovered':{'files':['dashboard/common/window_helper.py']}}
    with repair._recovery_mutation_locks(row):pass
    for name in ['cf/cleaner.lock','naver/pipeline-run.lock','kin-scheduler.lock','threads-scheduler.lock','content-maintenance.lock']:
        assert any(path.endswith(name) for path in observed)


def test_resource_recheck_uses_availability_changes_not_usage_drip_or_timestamps(tmp_path):
    from common.recovery_evidence import resource_availability
    path=tmp_path/'dashboard/data/live_snapshot.json';path.parent.mkdir(parents=True)
    def snapshot(value,checked):write(path,{'brains':{'quotas':{'agy':{'status':'collected','checkedAt':checked,'groups':[{'name':'Gemini','buckets':[{'remainingPercent':value}]}]}}}})
    snapshot(80,1);first=resource_availability(tmp_path)
    snapshot(79,2);assert resource_availability(tmp_path)==first
    snapshot(None,3);assert resource_availability(tmp_path)['agy']['groups']['Gemini'] is None
    snapshot(0,4);assert resource_availability(tmp_path)['agy']['groups']['Gemini'] is False
    snapshot(100,5);assert resource_availability(tmp_path)['agy']['groups']['Gemini'] is True


@pytest.mark.parametrize('native_status,native_attempts,expected_calls',[
    ('failed',1,1),('failed',2,0),('unknown',1,0),('running',1,0)])
def test_exact_native_conference_owns_retry_budget_for_legacy_recovery(tmp_path,monkeypatch,native_status,native_attempts,expected_calls):
    from common import project_autonomy as autonomy,conference_dispatch as conferences,work_agenda as agendas
    queue=tmp_path/'queue';queue.mkdir();state=tmp_path/'state.json';config=tmp_path/'config.json'
    write(config,{'enabled':True,'projects':['naver_blog']})
    monkeypatch.setattr(autonomy,'CONFIG',config);monkeypatch.setattr(autonomy,'STATE',state)
    monkeypatch.setattr(conferences,'QUEUE',queue);monkeypatch.setattr(agendas,'enabled',lambda:True)
    monkeypatch.setattr(agendas,'require',lambda **kwargs:{'id':'same-business'})
    identity='a'*64;conference_id='b'*64
    prior={'project':'naver_blog','workId':identity,'attempts':2,'requestedAt':1,
           'conference':{'agendaId':conference_id,'status':'conference_requested'}}
    (tmp_path/'project-work-recovery').mkdir()
    write(tmp_path/'project-work-recovery'/f'{identity}.json',prior)
    canonical={'status':native_status,'attempts':native_attempts,'businessAgendaId':'same-business','requestedAt':7}
    write(queue/f'{conference_id}.json',canonical)
    monkeypatch.setattr(autonomy,'recoverable_work',lambda project:[{'workId':identity,'date':'2026-10-25','identity':'soultin','slot':'07:40'}])
    request=Mock(return_value={'status':'conference_failed','agendaId':conference_id,'requestedAt':7})
    monkeypatch.setattr(conferences,'request',request)
    def retry():write(queue/f'{conference_id}.json',{**canonical,'status':'queued','attempts':2})
    resume=Mock(side_effect=retry);monkeypatch.setattr(conferences,'retry_active',resume)
    result=autonomy.recover_project_work('naver_blog',identity)
    assert resume.call_count==request.call_count==expected_calls
    if expected_calls:
        assert result['attempts']==2 and result['conferenceRequestedAt']==7
        assert len(result['attemptHistory'])==1


def test_team_receives_fresh_owned_recovery_result_without_source_reinvestigation(tmp_path,monkeypatch):
    from agents import crew_reasoning as crew
    from common import work_agenda as agendas,conference_dispatch as conferences
    monkeypatch.setattr(repair,'ROOT',tmp_path)
    monkeypatch.setattr(agendas,'enabled',lambda:True)
    identity='a'*64
    monkeypatch.setattr(agendas,'active',lambda:{'id':identity})
    monkeypatch.setattr(conferences,'QUEUE',tmp_path)
    path=repair._recovery_path('project-incident:'+identity[:24])
    row={'businessAgendaId':identity,'status':'resume_held','step':'verify','classification':{'kind':'retry_original','reason':'Current window observed'},
         'resumeResult':{'status':'unknown','reason':'conference_receipt_superseded','conference':{'agendaId':'b'*64}},'plan':{'secret':'never share'}}
    write(path,row);write(tmp_path/('b'*64+'.json'),{'businessAgendaId':identity,'status':'failed','attempts':1,'cookie':'never share'})
    observed=crew.recovery_progress()
    assert observed['classification']['kind']=='retry_original'
    assert observed['resumeOutcome']['reason']=='conference_receipt_superseded'
    assert observed['originalConference']['status']=='failed'
    assert 'never share' not in json.dumps(observed)
    row['businessAgendaId']='other';write(path,row)
    assert crew.recovery_progress()=={}
