"""Measured agenda costs remain separate from unknown legacy coverage."""
import datetime as dt
from common import llm_usage as usage, work_agenda as agendas
from common.collection_observability import load


def test_agenda_metrics_are_deduplicated_and_preserve_actual_route(tmp_path):
    now=dt.datetime(2026,10,25,7,tzinfo=usage.KST)
    call=dict(id='one',agendaId='a'*64,provider='codex',model='actual-model',reasoningEffort='high',
        startedAt=now.isoformat(),latencyMs=123,inputTokens=0,outputTokens=0,usageReports=0,rateLimitHeaders={})
    usage.record_call(call,'started',root=tmp_path,now=now)
    usage.record_call(call,'completed',root=tmp_path,now=now)
    # Aggregate deduplication protects the agenda receipt from a repeated observation.
    usage.record_call(call,'completed',root=tmp_path,now=now)
    usage.record_call(dict(id='tool',agendaId='a'*64,action='tool'),'action_failed',root=tmp_path,now=now)
    usage.record_call(dict(id='ui',agendaId='a'*64,action='click'),'action_completed',root=tmp_path,now=now)
    ledger=load(tmp_path/'dashboard/data/llm_usage_ledger.json')
    row=ledger['byAgenda']['a'*64]
    assert (row['modelCalls'],row['modelLatencyMs'],row['modelErrors'])==(1,123,0)
    assert row['routes']=={'codex|actual-model|high':1}
    assert row['toolRoundTrips']==1 and row['toolFailures']==1 and row['uiActions']==1
    assert ledger['byModel']['codex:actual-model']['usageReportedCalls']==0
    result=agendas.performance({'id':'b'*64,'activatedAt':1},ledger)
    assert result['modelCalls'] is None and result['toolRoundTrips'] is None
    assert result['verifiedCompletions'] is None and result['coverage']=='observed_calls_only'


def test_meter_attributes_only_validated_context(monkeypatch):
    monkeypatch.setattr(agendas,'current',lambda:None)
    monkeypatch.setattr(agendas,'require',lambda:(_ for _ in ()).throw(AssertionError('No ambient attribution')))
    assert usage.agenda_identity() is None
    monkeypatch.setattr(agendas,'current',lambda:{'id':'a'*64})
    monkeypatch.setattr(agendas,'require',lambda:{'id':'a'*64})
    assert usage.agenda_identity()=='a'*64
