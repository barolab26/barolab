import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock,patch
from cf_posting import pipeline_runner as runner


class PublisherWatchdogTests(unittest.TestCase):
    def run_case(self,progress,inflight=False):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);path=Path(temp.name)/'schedule.json'
        state={'items':[{'domain':'example.com','status':'processing','currentModel':{'at':0}}]};path.write_text(json.dumps(state))
        time=[0];calls=[0]
        process=Mock()
        def wait(timeout=None):
            if timeout is None:return 0
            calls[0]+=1;time[0]+=900 if progress else 301
            if progress and calls[0]==4:return 0
            if progress:
                state['items'][0]['currentModel']['at']=calls[0];path.write_text(json.dumps(state))
            raise subprocess.TimeoutExpired('fixture',timeout)
        process.wait.side_effect=wait
        with patch.object(runner,'publication_may_be_inflight',return_value=inflight):
            result=runner.wait_for_publisher_progress(process,path,'example.com',clock=lambda:time[0])
        return result,process,time[0]
    def test_progressing_work_can_finish_after_old_twenty_minute_cutoff(self):
        result,process,elapsed=self.run_case(True)
        self.assertEqual(result,0);self.assertGreater(elapsed,1200);process.kill.assert_not_called()
    def test_stalled_pre_submission_work_is_bounded(self):
        result,process,elapsed=self.run_case(False)
        self.assertEqual(result,-3);process.kill.assert_called_once()
    def test_unknown_submission_outcome_is_never_killed(self):
        result,process,_=self.run_case(False,True)
        self.assertEqual(result,0);process.kill.assert_not_called()

if __name__=='__main__':unittest.main()
