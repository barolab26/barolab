import datetime as dt
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from rich.console import Console
from server import mission_control as ui
from common.llm_usage import record_codex_usage


class CockpitTests(unittest.TestCase):
    def setUp(self):
        self.now=dt.datetime(2026,10,22,15,0,tzinfo=ui.KST)

    def test_daily_counts_exclude_reservations_old_dates_and_lifetime_totals(self):
        cf={'date':'2026-10-21','items':[{'status':'published','publicUrl':'https://example.com/a'}]}
        nv={'date':'2026-10-22','accounts':[{'account':'a','slots':[
            {'status':'done','publicationStatus':'reserved'}, {'status':'done','publicPublicationVerified':True,'publicUrl':'https://blog.naver.com/a/123'},
            {'status':'done','publicPublicationVerified':True,'publicUrl':'https://blog.naver.com/a/123'}]}]}
        kin={'counts':{'published_verified':999},'daily':{'date':'2026-10-22','publishedVerified':2}}
        rows=ui.channels(cf,nv,kin,self.now)
        self.assertEqual([r['done'] for r in rows],[None,1,2])
        self.assertIn('예약 1건',rows[1]['note'])
        self.assertEqual(sum(r['target'] for r in rows),43)

    def test_partial_write_uses_last_valid_value_and_then_recovers(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'state.json';cache=ui.JsonCache()
            path.write_text('{"date":"today"}')
            self.assertEqual(cache.read(path),{'date':'today'})
            path.write_text('{')
            self.assertEqual(cache.read(path),{'date':'today'})
            self.assertIn(path,cache.errors)
            path.write_text('{"date":"tomorrow"}')
            self.assertEqual(cache.read(path),{'date':'tomorrow'})
            self.assertNotIn(path,cache.errors)

    def test_completed_stage_and_stale_model_are_not_shown_running(self):
        at=self.now.timestamp()*1000
        events=[{'ownerAgent':'patch','ts':at-2000,'phase':'started','model':'actual','stage':'writer'},
                {'ownerAgent':'patch','ts':at-1000,'phase':'completed','stage':'writer'},
                {'ownerAgent':'publi','ts':at-181000,'phase':'started','stage':'writer','model':'old'}]
        rows=ui.crew_rows(events,[],{},self.now)
        self.assertEqual([r['state'] for r in rows],['IDLE']*6)
        self.assertFalse(any(r['model'] for r in rows))

    def test_running_models_and_three_log_rows_preserve_event_scope(self):
        at=self.now.timestamp()*1000
        events=[{'ownerAgent':'patch','ts':at,'phase':'started','model':'actual','stage':'writer'}]
        for i in range(8):events.append({'ownerAgent':'trace','ts':at-i*1000,'phase':'completed','stage':'read_agent_status'})
        events.append({'ownerAgent':'radar','ts':at,'phase':'failed','stage':'researcher'})
        rows=ui.crew_rows(events,[],{},self.now)
        self.assertEqual(rows[1]['model'],'actual')
        self.assertEqual(rows[1]['state'],'RUNNING')
        logs=ui.activity_log(events,{}, {},self.now)
        self.assertEqual(len(logs),3)
        self.assertEqual([r['alert'] for r in logs],[False,False,True])
        self.assertFalse(any('발행 완료' in r['text'] for r in logs))

    def test_synchronous_model_request_shows_assigned_calling_model(self):
        event={'ownerAgent':'patch','ts':self.now.timestamp()*1000,'phase':'requested',
               'requestedTo':'configured-model-runner','stage':'repair-diagnosis-model'}
        row=ui.crew_rows([event],[],{'patch':{'model':'selected-model'}},self.now)[1]
        self.assertEqual((row['state'],row['model']),('RUNNING','selected-model'))

    def test_frame_fits_24_rows_and_treats_source_as_plain_text(self):
        data={'channels':[dict(name='CF 블로그',done=4,target=16,note='[red]literal')],
              'crew':ui.crew_rows([],[],{},self.now),
              'logs':ui.activity_log([],{}, {},self.now),'ports':{p:True for p in ui.PORTS}}
        stream=io.StringIO();console=Console(file=stream,width=120,height=24,color_system=None)
        console.print(ui.render(data,self.now,height=24))
        text=stream.getvalue()
        self.assertLessEqual(len(text.splitlines()),24)
        for word in ('MISSION CONTROL','43건','6인','최근 완료','8790','[ 4/16]','25%','[red]literal'):
            self.assertIn(word,text)
        self.assertNotIn('성공 판정 아님',text)

    def test_reported_usage_is_atomic_accumulates_and_resets_on_kst_day(self):
        events=[{'type':'turn.completed','usage':{'input_tokens':100,'cached_input_tokens':70,'output_tokens':20}}]
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            record_codex_usage(events,'actual-model',root,self.now)
            record_codex_usage(events,'actual-model',root,self.now)
            path=root/'server/data/llm-usage.json';usage=json.loads(path.read_text())
            self.assertEqual(usage['totalTokens'],240)
            self.assertEqual(usage['byModel'],{'actual-model':240})
            self.assertEqual(ui.token_summary(usage,self.now),('240 / 한도 미설정',None))
            usage['dailyTokenBudget']=1000
            self.assertEqual(ui.token_summary(usage,self.now)[1],.24)
            record_codex_usage(events,'actual-model',root,self.now+dt.timedelta(days=1))
            self.assertEqual(json.loads(path.read_text())['totalTokens'],120)

    def test_port_probes_are_cached_between_collections(self):
        with tempfile.TemporaryDirectory() as directory, patch('socket.create_connection',side_effect=OSError) as probe:
            collector=ui.Collector(Path(directory))
            collector.collect();collector.collect()
            self.assertEqual(probe.call_count,5)
            self.assertTrue(collector.get()['cached'])


if __name__=='__main__':unittest.main()
