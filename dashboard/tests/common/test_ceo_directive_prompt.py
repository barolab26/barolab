import json
from dashboard.agents import synapse


def test_operating_directives_keep_complete_conditions_before_reference_cards(monkeypatch):
    tail='기존 총 실행 상한과 날짜·계정·예약 시각을 변경하지 않는다.'
    guidance='승인된 통합 수정안에 따라 실제 결과와 보고 수신을 확인한다. '*12+tail
    monkeypatch.setattr(synapse,'cached_index',lambda root:{'operatingDirectives':[
        {'active':True,'guidance':guidance,'roles':['jarvis'],'recordedAt':'2026-10-25T07:00:00+09:00'},
        {'active':True,'guidance':'다른 역할 전용','roles':['doctor']}]})
    result=synapse.recipe('수정안','jarvis')
    instructions=[json.loads(line) for line in result.splitlines() if line.startswith('{')]
    assert instructions[0]['principle']==guidance and tail in result
    assert '다른 역할 전용' not in result
