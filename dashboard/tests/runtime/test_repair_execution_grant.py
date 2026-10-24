"""A repair receipt authorizes one atomic execution without erasing the original cap."""
import hashlib
import json
from pathlib import Path
from unittest.mock import Mock
import pytest
from common import conference_dispatch as conference,repair_workflow as repair,project_autonomy as autonomy,coding_job
from common.collection_observability import write,load


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def repaired(tmp_path,monkeypatch):
    from common import work_agenda as agendas,recovery_evidence as evidence
    root=tmp_path;queue=root/'queue';queue.mkdir();repairs=root/'repairs';repairs.mkdir();jobs=root/'jobs';jobs.mkdir();job=jobs/'one';job.mkdir()
    monkeypatch.setattr(conference,'ROOT',root);monkeypatch.setattr(conference,'QUEUE',queue)
    monkeypatch.setattr(repair,'ROOT',repairs);monkeypatch.setattr(coding_job,'JOB_ROOT',jobs)
    engine=root/'naver_blog_posting/posting.py';engine.parent.mkdir();engine.write_text('frozen boundary')
    monkeypatch.setattr(conference,'NAVER_SUBMISSION_BOUNDARY_SHA256',sha(engine))
    folder=root/'naver_blog_posting/output/scheduled/2026-10-25/soultin-0740';folder.mkdir(parents=True)
    write(folder/'editor-content.json',{'title':'approved'})
    source=root/'dashboard/common/fix.py';source.parent.mkdir(parents=True);source.write_text('fixed=True')
    args={'action':'naver','date':'2026-10-25','account':'soultin','slot':'07:40'}
    current={'id':'business','project':'naver_blog','source':{'kind':'parameters','arguments':args}}
    original={'businessAgendaId':'business','kind':'parameters','arguments':args,'status':'failed','attempts':2,'failureReason':'xclip'}
    identity=hashlib.sha256(json.dumps(['parameters',args],sort_keys=True).encode()).hexdigest();file=queue/(identity+'.json');write(file,original)
    target={'workId':'w','identity':'soultin','date':'2026-10-25','slot':'07:40','submissionStarted':False,'artifactFolder':str(folder),'project':'naver_blog'}
    journal=root/'dashboard/data/naver/automation-journal.json';journal.parent.mkdir(parents=True)
    write(journal,{'attempts':[{'account':'soultin','publicationDate':'2026-10-25','scheduledSlot':'07:40','submissionStarted':False,'preCommitIntent':False,'phase':'failed'}]})
    write(journal.parent/'public-verification.json',{'evidence':[]})
    validation={'status':'isolated_verified','candidateSha256':'candidate','sandbox':{'enforced':True},'results':[{'returncode':0}]}
    write(job/'validation.json',validation)
    app={'status':'applied','productionApplied':True,'sourceRoot':str(root),'candidateSha256':'candidate','validationSha256':sha(job/'validation.json'),'before':{'dashboard/common/fix.py':'old'},'after':{'dashboard/common/fix.py':sha(source)}}
    write(job/'application.json',app)
    plan={'project':'naver_blog','projectRoot':str(root),'originalRequestPath':str(file),'originalRequestSha256':sha(file),'workTarget':target,'approvedDocumentSha256':sha(folder/'editor-content.json')}
    digest=hashlib.sha256(json.dumps(plan,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    row={'taskId':'task','businessAgendaId':'business','step':'resume','status':'ready','plan':plan,'planSha256':digest,'job':{'candidateSha256':'candidate','jobDir':str(job)},'application':{'evidencePath':str(job/'application.json'),'evidenceSha256':sha(job/'application.json')},'validation':{'validationSha256':sha(job/'validation.json')}}
    write(repair._recovery_path('task'),row)
    monkeypatch.setattr(agendas,'require',lambda **kwargs:current);monkeypatch.setattr(agendas,'running',lambda row:[]);monkeypatch.setattr(agendas,'progress',lambda *args:None)
    monkeypatch.setattr(autonomy,'recoverable_work',lambda project:[target])
    return current,original,row,digest,file,folder,journal,source


def test_verified_receipt_consumed_once_and_all_original_attempts_remain(repaired):
    current,original,row,digest,file,*_=repaired
    result=conference.retry_active(repair_task_id='task',repair_plan_sha256=digest)
    saved=load(file)
    assert result['status']=='queued' and saved['attempts']==3
    assert saved['executionGeneration']['generationId']==2
    assert saved['attemptHistory'][0]['failureReason']=='xclip'
    saved['status']='failed';write(file,saved)
    with pytest.raises(ValueError):conference.retry_active(repair_task_id='task',repair_plan_sha256=digest)
    assert load(file)['attempts']==3


@pytest.mark.parametrize('failure',['receipt','intent','missing_intent','missing_submission','submitted','document','patch','validation','running','wrong_owner','bad_hash','cap'])
def test_unsafe_or_incomplete_evidence_cannot_issue_grant(repaired,monkeypatch,failure):
    from common import work_agenda as agendas
    current,original,row,digest,file,folder,journal,source=repaired
    if failure=='receipt':write(folder/'reservation-evidence.json',{'submissionStatus':'submitting'})
    if failure=='intent':
        data=load(journal);data['attempts'][0]['preCommitIntent']=True;write(journal,data)
    if failure=='missing_intent':
        data=load(journal);data['attempts'][0].pop('preCommitIntent');write(journal,data)
    if failure in ('missing_submission','submitted'):
        data=load(journal);data['attempts'][0]['submissionStarted']=None if failure=='missing_submission' else True;write(journal,data)
    if failure=='document':write(folder/'editor-content.json',{'title':'changed'})
    if failure=='patch':source.write_text('different')
    if failure=='validation':(Path(row['job']['jobDir'])/'validation.json').write_text('{}')
    if failure=='running':monkeypatch.setattr(agendas,'running',lambda row:[{'pid':42}])
    if failure=='wrong_owner':current['id']='other'
    if failure=='bad_hash':digest='0'*64
    if failure=='cap':original['attempts']=3;write(file,original)
    with pytest.raises((ValueError,KeyError)):conference.retry_active(repair_task_id='task',repair_plan_sha256=digest)
    assert load(file)['status']=='failed' and 'executionGeneration' not in load(file)


def test_precommit_receipt_is_durable_before_return(tmp_path,monkeypatch):
    from common import dashboard_jobs as jobs
    events=[];real=jobs.os.fsync
    def sync(fd):events.append('sync');real(fd)
    monkeypatch.setattr(jobs.os,'fsync',sync)
    file=tmp_path/'reservation-evidence.json';jobs.write(file,{'submissionStatus':'submitting'})
    assert load(file)['preCommitIntent'] is True and events==['sync','sync']


def test_new_failure_archives_prior_revision_and_rejects_old_phase_token(repaired,monkeypatch):
    from common import work_agenda as agendas,recovery_evidence,channel_parameters
    from server import project_health
    current,original,row,digest,file,folder,journal,source=repaired
    source_doc=source.parents[1]/'data/naver/automation-status.json';write(source_doc,{'accounts':[]})
    row.update(status='resume_held',resumeAttempted=True,steps={'resume':{'finishedAt':1}})
    row['plan']['failure']=[{'reason':'old error','errorType':'ValueError'}]
    row['planSha256']=hashlib.sha256(json.dumps(row['plan'],sort_keys=True,ensure_ascii=False).encode()).hexdigest();old=row['planSha256'];write(repair._recovery_path('task'),row)
    monkeypatch.setattr(repair,'_recovery_path',lambda task:repair.ROOT/'row.json')
    write(repair.ROOT/'row.json',row)
    monkeypatch.setattr(project_health,'ROOT',conference.ROOT)
    monkeypatch.setattr(project_health,'SOURCES',[('naver_blog','unused',str(source_doc.relative_to(conference.ROOT)))])
    monkeypatch.setattr(recovery_evidence,'failure_targets',lambda *a:[row['plan']['workTarget']])
    row['plan']['workTarget']['submissionStarted']=False
    monkeypatch.setattr(agendas,'require',lambda:current)
    # Use the actual deterministic task identity when simulating an existing revision.
    row['taskId']='project-incident:business';write(repair.ROOT/'row.json',row)
    result=repair.prepare_conference_recovery();saved=load(repair.ROOT/'row.json')
    assert result['planSha256']!=old and saved['step']=='discover' and not saved['resumeAttempted']
    archive=Path(saved['recoveryRounds'][0]['path']);assert load(archive)['steps']==row['steps']
    assert repair.prepare_conference_recovery()['planSha256']==result['planSha256']
    assert sha(archive)==saved['recoveryRounds'][0]['sha256']
    with pytest.raises(ValueError):repair._recovery_row(row['taskId'],old)


def test_legacy_missing_intent_is_not_retroactively_converted_to_false(tmp_path):
    from common import dashboard_jobs as jobs
    file=tmp_path/'automation-journal.json'
    old={'phase':'failed','submissionStarted':False}
    new={'phase':'started','submissionStarted':False}
    jobs.write(file,{'attempts':[old,new]})
    saved=load(file)['attempts']
    assert 'preCommitIntent' not in saved[0] and saved[1]['preCommitIntent'] is False


def test_concurrent_consumers_cannot_duplicate_the_same_grant(repaired):
    from concurrent.futures import ThreadPoolExecutor
    _,_,_,digest,file,*_=repaired
    def attempt():
        try:return conference.retry_active(repair_task_id='task',repair_plan_sha256=digest)['status']
        except ValueError:return 'held'
    with ThreadPoolExecutor(2) as pool:results=list(pool.map(lambda _:attempt(),range(2)))
    assert sorted(results)==['held','queued'] and load(file)['attempts']==3
