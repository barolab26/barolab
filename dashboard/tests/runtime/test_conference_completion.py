"""A queued meeting and an idle scheduler are never publication evidence."""
import json
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


def test_unverified_conference_outcome_is_not_success(tmp_path):
    identity='a'*64
    row={'agendaId':identity,'kind':'threads','requestedAt':10,'status':'completed','outcomes':[{'outcome':'게시 확인 중','publicationVerified':False}]}
    (tmp_path/(identity+'.json')).write_text(json.dumps(row))
    with patch.object(conferences,'QUEUE',tmp_path):
        terminal,_=autonomy.terminal_result({'conferenceAgendaId':identity,'conferenceRequestedAt':10,'project':'threads'})
    assert terminal['status']=='unknown' and terminal['ok'] is False
    assert terminal['publicationVerified'] is False
