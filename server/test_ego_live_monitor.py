import datetime
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from server import ego_live_monitor as hud

class MonitorTests(unittest.TestCase):
    def test_all_projects_preserve_status_date_and_unknown_counts(self):
        now = datetime.datetime(2026,10,21,tzinfo=hud.KST)
        projects = [{'id':str(i),'title':'프로젝트'+str(i),'status':'stale','counts':{'review_required':1},
                     'source':{'sourceDate':'2026-10-20'},'verifiedPublicCount':None} for i in range(6)]
        text = '\n'.join(hud.render_lines({'observedAt':now.timestamp()-100,'projects':projects},[],now=now))
        for i in range(6): self.assertIn('프로젝트'+str(i),text)
        self.assertIn('지난 관측',text)
        self.assertIn('2026-10-20',text)
        self.assertIn('공개 확인:미관측',text)
        self.assertNotIn('전체 완료',text)
        self.assertNotIn('/16',text)

    def test_missing_snapshot_and_running_receipt_never_complete(self):
        row={'taskId':'task-1','status':'awaiting_completion','results':[{'tool':'repair_cf_known_failure',
             'result':{'executorReceipt':{'executor':'ego-lite','status':'running','completed':False}}}]}
        text='\n'.join(hud.render_lines({},[row],now=datetime.datetime.now(hud.KST)))
        self.assertIn('결과 대기',text)
        self.assertIn('실행 중',text)
        self.assertIn('EGO 실행 기록',text)
        self.assertIn('원천 자료 미관측',text)
        self.assertNotIn('Gemini',text)

    def test_terminal_repair_preserves_executor_origin_without_old_running_state(self):
        row={'taskId':'repair','status':'held','results':[{'tool':'repair_cf_known_failure',
             'initialResult':{'executorReceipt':{'executor':'ego-lite','status':'running','completed':False}},
             'result':{'status':'held'}}]}
        text='\n'.join(hud.render_lines({},[row],now=datetime.datetime.now(hud.KST)))
        self.assertIn('EGO 실행 기록',text)
        self.assertIn('보류',text)
        self.assertNotIn('running',text)

    def test_malformed_queue_skips_without_writing(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'bad.json';p.write_text('bad')
            (Path(d)/'good.json').write_text('{"taskId":"actual","status":"queued"}')
            self.assertEqual(hud.request_rows(Path(d))[0]['taskId'],'actual')
            self.assertEqual(p.read_text(),'bad')

    def test_fresh_collection_does_not_refresh_old_source(self):
        now=datetime.datetime(2026,10,21,12,tzinfo=hud.KST)
        row={'title':'네이버','status':'stale','source':{'fresh':False,'sourceDate':'2026-10-20',
             'sourceCheckedAt':'2026-10-20T12:00:00+09:00'}}
        text='\n'.join(hud.render_lines({'observedAt':now.timestamp(),'projects':[row]},[],now=now))
        self.assertIn('자료 다시 읽은 시각',text)
        self.assertIn('원천 오래됨 / 미확인',text)
        self.assertIn('86400초 전',text)
        self.assertIn('업무 실행 및 원천 데이터 갱신을 의미하지 않음',text)

    def test_old_active_request_remains_in_activity_below_recent_completed(self):
        now=datetime.datetime.now(hud.KST)
        rows=[{'taskId':str(i),'status':'completed','createdAt':100+i} for i in range(5)]
        rows.append({'taskId':'active','status':'acknowledged','claimedAt':now.timestamp(),
            'actions':[{'agent':'patch','tool':'read_agent_status'}],
            'latestAction':{'kind':'staff_model','agent':'patch','state':'calling','observedAt':now.timestamp()}})
        text='\n'.join(hud.render_lines({},rows,now=now,activity={'cf':{'state':'idle','stage':None,'lastActionAt':None},'coverage':'CF·네이버 연결'}))
        self.assertIn('④ EGO 현재 활동',text)
        self.assertIn('패치 답변 모델 호출 중',text)
        self.assertIn('CF 파이프라인: 대기',text)
        self.assertIn('시각 미관측',text)

    def test_request_reader_does_not_drop_older_active_rows(self):
        import json
        with tempfile.TemporaryDirectory() as d:
            for i in range(6):
                (Path(d)/f'{i}.json').write_text(json.dumps({'taskId':str(i),'createdAt':i,'status':'acknowledged' if i==0 else 'completed'}))
            self.assertEqual(len(hud.request_rows(Path(d))),6)
            self.assertEqual(hud.request_rows(Path(d))[-1]['status'],'acknowledged')

    def test_old_running_or_nonfinite_timestamp_does_not_claim_current_execution(self):
        now=datetime.datetime.now(hud.KST)
        rows=[{'status':'acknowledged','latestAction':{'kind':'staff_model','state':'calling','agent':'patch','observedAt':now.timestamp()-121}}]
        text='\n'.join(hud.render_lines({},rows,now=now))
        self.assertIn('현재 지속 여부 미확인',text)
        for value in (float('nan'),float('inf')):
            self.assertEqual(hud.time_label(value,now),'시각 미관측')

    def test_default_ego_only_delegates_monitor(self):
        import ego_lite_runner as ego
        with patch.object(hud,'main',return_value=0) as monitor, patch.object(ego,'run_cf_catch_up') as cf:
            self.assertEqual(ego.main_loop(),0)
            monitor.assert_called_once();cf.assert_not_called()
        with patch.object(hud,'main',return_value=0), patch('dashboard.metrics.collector_lock') as lock:
            self.assertEqual(ego.main([]),0)
            lock.assert_not_called()
        self.assertFalse(hasattr(ego,'poll_and_execute_gemini_command'))
        self.assertFalse(hasattr(ego,'get_last_gemini_response_sync'))

if __name__=='__main__': unittest.main()
