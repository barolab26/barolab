import datetime as dt
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch

from rich.console import Console
from server import cockpit_telemetry as probe,cockpit_panels as view,mission_control as ui


class TelemetryTests(unittest.TestCase):
    def test_credit_numbers_keep_key_cap_distinct_from_account_balance(self):
        key=Mock(status_code=200);key.json.return_value={'data':{'usage':2.25,'limit':10,'limit_remaining':7.75}}
        credits=Mock(status_code=200);credits.json.return_value={'data':{'total_credits':30,'total_usage':5}}
        with patch.object(probe.requests,'get',side_effect=[key,credits]) as get:
            result=probe.credit_probe({'OPENROUTER_API_KEY':'private-key'})
        self.assertEqual((result['usage'],result['limit_remaining'],result['balance']),(2.25,7.75,25))
        self.assertNotIn('private-key',str(result));self.assertEqual(get.call_count,2)
    def test_no_key_never_calls_remote_and_never_claims_zero_balance(self):
        with patch.object(probe.requests,'get') as get:result=probe.credit_probe({})
        get.assert_not_called();self.assertNotIn('balance',result)
    def test_cdp_probe_sanitizes_url_and_does_not_invent_active_tab(self):
        response=Mock();response.json.return_value=[{'type':'page','id':'a','title':'Title','url':'https://user:pass@example.com/a?token=secret#private'}]
        with patch.object(probe.requests,'get',return_value=response) as get:
            result=probe.fleet_probe(probe.FLEET[0])
        self.assertTrue(result['online']);self.assertEqual(result['tabs'][0]['url'],'https://example.com/a')
        self.assertEqual(result['selection'],'열린 탭');self.assertEqual(get.call_args.kwargs['timeout'],.3)
    def test_high_frame_fills_height_with_six_panels_and_plain_source_text(self):
        now=dt.datetime(2026,10,22,15,tzinfo=ui.KST)
        data={'channels':[{'name':'CF 블로그','done':4,'target':16,'note':'[red]literal'}],
              'crew':ui.crew_rows([],[],{},now),'remote':{'fleet':[dict(port=p,account=a,blog=b,purpose=u,online=True,tabs=[{'title':'[red]Title','url':'https://example.com/'}]) for p,a,b,u in probe.FLEET]}}
        stream=io.StringIO();console=Console(file=stream,width=144,height=76,color_system=None)
        console.print(view.render(data,now,76));text=stream.getvalue()
        self.assertEqual(len(text.splitlines()),76);self.assertEqual(sum(view.panel_sizes(76)),76)
        for title in ('MISSION CONTROL','BRAIN','BROWSER FLEET','PIPELINE','ACTIVE CREW','VAULT','[red]Title','[red]literal'):
            self.assertIn(title,text)
        self.assertNotIn('성공 판정 아님',text)
        self.assertIn('┗',text.splitlines()[-1])
    def test_missing_daily_revenue_is_not_zero_and_duplicate_adpost_is_not_added(self):
        now=dt.datetime(2026,10,22,15,tzinfo=ui.KST)
        src={'category':'adsense','currency':'USD','daily':{'2026-10-20':'0.03'}}
        result='\n'.join(view.revenue_summary({'months':{'2026-10':{'sources':[src]}}},{},now))
        self.assertIn('오늘 집계 대기',result);self.assertIn('$0.03',result);self.assertNotIn('오늘 $0.00',result)
    def test_codex_subscription_limit_and_positive_extra_credits_are_both_visible(self):
        now=dt.datetime(2026,10,22,15,tzinfo=ui.KST)
        data={'remote':{'codexQuota':{'status':'collected','buckets':{'codex':{
            'primary':{'usedPercent':100,'windowDurationMins':10080},
            'credits':{'hasCredits':True,'unlimited':False,'balance':'39263.1127530000'}}}}}}
        text='\n'.join(view.brain_lines(data,now))
        self.assertIn('잔여 0%',text);self.assertIn('39,263.11 크레딧',text)
        self.assertNotIn('$39,263',text)

    def test_all_stages_match_and_editorial_precedes_research(self):
        for stage,wanted in [('keyword-selector',1),('researcher',2),('editorial-query',3),('writer',4),('reviewer',5),('최종발행',6)]:
            self.assertEqual(view.stage_number(stage),wanted)

if __name__=='__main__':unittest.main()
