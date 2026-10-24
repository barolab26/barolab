import json
import math
from datetime import datetime, timezone
from unittest.mock import Mock
import pytest
from server import cockpit_telemetry as telemetry, cockpit_panels as panels


@pytest.mark.parametrize('value',[0,91.97])
def test_kie_balance_uses_readonly_api_without_leaking_key(monkeypatch,value):
    get=Mock(return_value=Mock(status_code=200,json=lambda:{'code':200,'data':value,'private':'secret'}))
    monkeypatch.setattr(telemetry.requests,'get',get)
    result=telemetry.provider_credit_probe('kie',{'KIE_API_KEY':'secret'})
    assert result['status']=='collected' and result['balance']==value
    assert get.call_args.args[0]=='https://api.kie.ai/api/v1/chat/credit'
    assert get.call_args.kwargs['allow_redirects'] is False
    assert 'secret' not in json.dumps(result)


@pytest.mark.parametrize('value',[True,-1,'12',None,math.nan,math.inf])
def test_invalid_kie_balances_are_unknown_not_zero(monkeypatch,value):
    monkeypatch.setattr(telemetry.requests,'get',lambda *a,**k:Mock(status_code=200,json=lambda:{'code':200,'data':value}))
    assert telemetry.provider_credit_probe('kie',{'KIE_API_KEY':'secret'})['balance'] is None


def test_jev_no_public_balance_api_does_not_make_paid_or_guessed_requests(monkeypatch):
    get=Mock();monkeypatch.setattr(telemetry.requests,'get',get)
    result=telemetry.provider_credit_probe('jev',{'JEV_BAROINCOME_API_KEY':'secret'})
    assert result['balance'] is None and '미수집' in result['status']
    get.assert_not_called()


def test_display_distinguishes_missing_zero_and_stale_balances():
    now=datetime.now(timezone.utc)
    data={'remote':{'kie':{'status':'collected','balance':0,'checkedAt':now.timestamp()},'jev':{'balance':None}}}
    lines=panels.brain_display(data,now)['rows']
    assert '[KIE] 잔여 0.00 credits' in lines and '[JEV] 잔액 미수집' in lines
    data['remote']['kie']['checkedAt']-=181
    assert not any('잔여 0.00 credits' in r for r in panels.brain_display(data,now)['rows'])
