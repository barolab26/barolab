import json
from datetime import datetime,timedelta
from pathlib import Path
from unittest.mock import Mock
import pytest
from common.collection_observability import write
from server import mission_control as mc,cockpit_panels as panels
from agents import crew_reasoning as crew


@pytest.fixture
def context(tmp_path):
    collector=mc.Collector(tmp_path);identity='a'*64
    data=tmp_path/'dashboard/data';rows=data/'publication-conferences/operations';rows.mkdir(parents=True)
    now=datetime(2026,10,25,4,tzinfo=mc.KST)
    write(data/'active-agenda.json',{'enabled':True,'activeId':identity})
    row={'id':identity,'kind':'conference','title':'네이버 예약 · soultin · 2026-10-25 · 07:40','project':'naver_blog','status':'recovering',
         'activatedAt':(now-timedelta(minutes=10)).timestamp(),'processes':[],
         'source':{'arguments':{'account':'soultin','date':'2026-10-25','slot':'07:40','cookie':'PRIVATE'}}}
    write(rows/(identity+'.json'),row)
    return collector,row,rows,now


def test_collector_exposes_bound_target_and_observed_process_without_private_metadata(context):
    collector,row,rows,now=context;control=collector.read_agenda()
    assert control['active']['target']['account']=='soultin'
    assert not control['active']['processObserved']
    assert 'PRIVATE' not in json.dumps(control)
    write(collector.root/'dashboard/data/active-agenda.json',{'enabled':True,'activeId':None})
    assert collector.read_agenda()=={'enabled':True,'active':None}


def test_closed_or_switched_agenda_is_not_reconstructed_as_current(context):
    collector,row,rows,now=context
    row['status']='closed';write(rows/(row['id']+'.json'),row)
    assert collector.read_agenda()['active'] is None


def test_automatic_recheck_time_is_visible_in_the_same_monitor_projection(context):
    collector,row,rows,now=context
    row['recoveryWatch']={'state':'waiting_for_change','nextCheckAt':now.timestamp()+300,'checks':2}
    write(rows/(row['id']+'.json'),row)
    control=collector.read_agenda()
    lines=panels.pipeline_lines({'agendaControl':control},now)
    assert control['active']['automaticRecovery']['checks']==2
    assert any('자동 재확인: 04:05:00' in line for line in lines)


def test_ego_uses_current_soultin_agenda_and_labels_old_stone_record_as_history(context):
    collector,row,rows,now=context
    data={'collectedAt':now.timestamp(),'channels':mc.channels({}, {}, {},now),'agendaControl':collector.read_agenda(),
          'workflow':{'status':'processing','account':'stone0747 (지원금)','scheduledSlot':'12:40','date':'2026-10-25',
                      'updatedAt':'01:16:27','stageName':'에디터 입력','detailMessage':'OLD TOPIC'},
          'events':[{'stage':'editorial-scope','outputKind':'UNRELATED CF ADVICE','ts':1}]}
    shared=mc.shared_snapshot(data);lines=shared['panels'][3]
    assert lines[0].startswith('현재 안건 · 네이버 예약 · soultin')
    assert any('과거 실행 기록' in line and 'stone0747' in line for line in lines)
    assert not any(line.startswith('네이버 stone0747') or 'OLD TOPIC' in line or 'UNRELATED CF ADVICE' in line for line in lines)
    assert shared['agendaControl']==data['agendaControl']


@pytest.mark.parametrize('alive,fresh,expected',[(False,True,False),(True,False,False),(True,True,True)])
def test_pipeline_stage_needs_same_target_live_owner_and_observation_after_activation(context,alive,fresh,expected):
    collector,row,rows,now=context;control=collector.read_agenda();control['active']['processObserved']=alive
    workflow={'status':'processing','account':'soultin (시니어)','blogId':'soultin01','scheduledSlot':'07:40','date':'2026-10-25',
              'updatedAt':'03:55:00' if fresh else '01:16:00','stageName':'에디터 입력','detailMessage':'CURRENT TOPIC'}
    lines=panels.pipeline_lines({'agendaControl':control,'workflow':workflow},now)
    assert any('CURRENT TOPIC' in line for line in lines)==expected


def test_staff_reads_exact_shared_execution_evidence_without_extra_collector(context,monkeypatch):
    collector,row,rows,now=context;monkeypatch.setattr(crew,'ROOT',collector.root)
    snapshot=mc.shared_snapshot({'collectedAt':now.timestamp(),'channels':mc.channels({}, {}, {},now),'agendaControl':collector.read_agenda()})
    write(collector.root/'dashboard/data/live_snapshot.json',snapshot)
    result=crew.read_evidence({'name':'execution'})
    assert result['data']['revision']==snapshot['revision']
    assert result['data']['agendaControl']['active']['target']['account']=='soultin'
    assert result['data']['pipelinePanel']==snapshot['panels'][3]


def test_staff_browser_observation_includes_window_mapping_only_within_project_scope(monkeypatch):
    from common import ubuntu_naver_browser as browser
    import playwright.sync_api as playwright
    monkeypatch.setattr(browser,'account_paths',lambda port:(None,Path('/registered-profile'),None))
    monkeypatch.setattr(browser,'process_identity',lambda port,profile:123)
    inspect=Mock(return_value={'status':'observed','display':':11','wmPid':123,'mapped':None})
    monkeypatch.setattr(browser,'inspect_workflow_window',inspect)
    manager=Mock();manager.return_value.__enter__=Mock();manager.return_value.__exit__=Mock()
    manager.return_value.__enter__.return_value.chromium.connect_over_cdp.return_value.contexts=[]
    monkeypatch.setattr(playwright,'sync_playwright',manager)
    result=crew.browser_observe({'permissions':{'projects':['naver_blog']}},{'port':9334})
    assert result['windowMapping']['display']==':11' and result['browserStarted'] is False
    inspect.assert_called_once_with(9334);inspect.reset_mock()
    with pytest.raises(ValueError):crew.browser_observe({'permissions':{'projects':['naver_kin']}},{'port':9334})
    inspect.assert_not_called()


def test_recovery_evidence_selection_is_applied_before_large_record_is_bounded(tmp_path,monkeypatch):
    from common import repair_workflow
    path=tmp_path/'recovery.json'
    write(path,{'taskId':'known-task','status':'held','classification':{'kind':'inspect','reason':'Needs window mapping'},
                'observation':{'large':'x'*40000},'inspection':{'status':'needs_evidence'}})
    monkeypatch.setattr(repair_workflow,'_recovery_path',lambda identity:path)
    result=crew.read_evidence({'name':'recovery_plan:known-task','select':['classification']})
    assert result['data']=={'kind':'inspect','reason':'Needs window mapping'}
    assert result['selection']==['classification']
    assert crew.read_evidence({'name':'recovery_plan:known-task','select':['inspection']})['data']=={'status':'needs_evidence'}
    with pytest.raises(ValueError,match='Private'):crew.read_evidence({'name':'recovery_plan:known-task','select':['access_token']})
    with pytest.raises(ValueError,match='nested path'):crew.read_evidence({'name':'recovery_plan:known-task','select':['status','classification']})


def test_activity_projection_keeps_owner_evidence_timing_and_both_ack_receipts(context):
    collector,row,rows,now=context
    identity='b'*64;row['controllerGoalId']=identity
    row['events']={'staff_result':{'receivedAt':1},'closing':{'receivedAt':2}}
    write(rows/(row['id']+'.json'),row)
    folder=collector.root/'dashboard/data/chats/reasoning-goals';folder.mkdir(parents=True)
    write(folder/(identity+'.json'),{'actor':'patch','updatedAt':now.timestamp(),
        'progress':{'summary':'정확한 원인 코드 확인','phase':'진단'},'observations':[{'tool':'read_source','observedAt':now.timestamp(),'result':{'ok':False}}],
        'discussion':[{'modelLatencyMs':200}], 'lastRoute':{'provider':'codex','model':'actual','reasoningEffort':'high'}})
    activity=collector.read_agenda()['active']['activity']
    assert activity['owner']=='patch' and activity['lastResult']=='read_source'
    assert activity['modelLatencyMs']==200 and activity['toolFailures']==1
    assert activity['reportAcknowledgments']=={'staff_result':1,'closing':2}
