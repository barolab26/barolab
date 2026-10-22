import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import patch

from common import recovery_evidence as evidence, coding_job, project_autonomy as autonomy


class RecoveryEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def save(self, name, value):
        path = self.root / name; path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value)); return path

    def test_held_work_rechecks_changed_evidence_without_replaying_operation(self):
        from common import repair_workflow as repair
        path=self.save('recovery/work.json', {'type':'project_recovery_v1','status':'evidence_hold',
            'plan':{'workTarget':{'workId':'original'}},'discovered':{'schemaVersion':3},
            'inspection':{'diagnosis':'old evidence'}})
        with patch.object(repair,'ROOT',path.parent), patch.object(repair,'_discover_recovery',return_value={'schemaVersion':4}), \
                patch('server.agent_tools.enqueue_staff_request') as enqueue:
            self.assertTrue(repair.dispatch_project_recovery_once())
            row=json.loads(path.read_bytes())
            self.assertEqual((row['status'],row['step']),('ready','classify'))
            self.assertNotIn('inspection',row)
            enqueue.assert_not_called()

    def test_public_probe_keeps_response_proof_when_text_is_private(self):
        from cf_posting import pipeline_runner as runner
        folder=self.root/'cf_posting/output/original/run'
        folder.mkdir(parents=True)
        (folder/'handoff.json').write_text('{"slug":"original"}')
        page=SimpleNamespace(text='<article>contact@example.com</article>',content=b'actual body',status_code=200)
        with patch.object(runner,'ALL_DOMAINS',['example.com']), \
                patch.object(runner,'read_document',return_value={}), \
                patch.object(runner,'published_inventory',return_value=[{'id':1,'slug':'original','title':'Original'}]), \
                patch('requests.get',return_value=page):
            result=evidence.public_work_observation(self.root,{'project':'cf_blog','identity':'example.com','artifactFolder':str(folder)})
        self.assertEqual(result['status'],'observed')
        self.assertEqual(result['candidates'][0]['bodySha256'],hashlib.sha256(page.content).hexdigest())
        self.assertNotIn('contact@example.com',json.dumps(result))

    def test_authoritative_naver_latest_attempt_excludes_already_verified_work(self):
        self.save('naver_blog_posting/data/automation-journal.json', {'attempts': [
            {'account':'a','publicationDate':'2026-10-21','scheduledSlot':'11:00','phase':'failed'},
            {'account':'a','publicationDate':'2026-10-21','scheduledSlot':'11:00','phase':'verified'},
            {'account':'b','publicationDate':'2026-10-22','scheduledSlot':'19:00','phase':'material_required',
             'failureReason':'Actual source material missing'}]})
        targets = evidence.failure_targets(self.root, 'naver_blog', {'accounts':[{'status':'unknown'}]})
        self.assertEqual([t['identity'] for t in targets], ['b'])
        self.assertEqual(targets[0]['failure'], 'Actual source material missing')

    def test_host_error_literal_locates_real_function_without_traceback(self):
        path = self.root / 'cf_posting/pipeline_runner.py'; path.parent.mkdir()
        function = 'def fail():\n    label = "Required original material missing: "\n    raise ValueError(label + "detail")\n'
        path.write_text('# padding\n' * 12000 + function)
        frames = evidence.error_source_frames(self.root, 'cf_blog', 'ValueError: Required original material missing: detail')
        self.assertEqual(len(frames), 1)
        region = coding_job.derive_edit_regions(self.root, ['cf_posting/pipeline_runner.py'], '', source_frames=frames)
        self.assertEqual(region['cf_posting/pipeline_runner.py'], function)
        self.assertEqual(evidence.error_source_frames(self.root, 'cf_blog', 'Unrelated failure'), [])

    def test_same_question_capture_adapter_and_artifact_hash_binding(self):
        folder = 'cf_posting/output/same-question/run'
        self.save(folder+'/handoff.json', {'domain':'example.com','slug':'same-question','runId':'original'})
        path = self.save(folder+'/prewriter-acquisition-request.json', {'status':'answer_inputs_required',
            'readerGoal':{'question':'original question'},'missingInputs':[{'kind':'actual_capture'}]})
        target = {'project':'cf_blog','identity':'example.com','artifactFolder':'output/same-question/run'}
        packet = evidence.task_evidence(self.root, target)
        self.assertEqual(packet['inputCapability']['originalRunId'], 'original')
        ref = next(a for a in packet['artifacts'] if a['path'] == str(path))
        self.assertEqual(ref['sha256'], hashlib.sha256(path.read_bytes()).hexdigest())
        self.save(folder+'/article.json', {})
        self.assertIsNone(evidence.task_evidence(self.root, target)['inputCapability'])

    def test_artifacts_cannot_escape_local_output_or_follow_symlink(self):
        outside = self.root / 'private'; outside.mkdir()
        target = {'project':'cf_blog','artifactFolder':str(outside)}
        self.assertIsNone(evidence.artifact_folder(self.root, target))
        folder = self.root/'cf_posting/output';folder.mkdir(parents=True)
        (folder/'escape').symlink_to(outside, target_is_directory=True)
        self.assertIsNone(evidence.artifact_folder(self.root, {**target,'artifactFolder':'output/escape'}))

    def test_naver_misalignment_collects_and_prepares_same_question_once(self):
        from common import repair_workflow
        import naver_blog_posting
        folder = self.root/'naver_blog_posting/output/acc/original';folder.mkdir(parents=True)
        target={'project':'naver_blog','identity':'acc','date':'2026-10-22','slot':'19:00',
                'workId':'original-work','artifactFolder':str(folder)}
        self.save('naver_blog_posting/output/acc/original/handoff.json',{'stages':[]})
        self.save('naver_blog_posting/output/acc/original/preparation-context.json',
            {'account':'acc','publicationDate':'2026-10-22','scheduledSlot':'19:00','runOptions':{},'strategyOverride':None})
        self.save('naver_blog_posting/output/acc/original/keyword-demand-alignment.json',
            {'inputs':{'readerQuestion':'Same original question?'}})
        original=self.save('naver_blog_posting/output/acc/original/keyword-title-original.json',
            {'title':'Same original subject'})
        before=original.read_bytes()
        cap=evidence.task_evidence(self.root,target)['inputCapability']
        self.assertEqual(cap['readerQuestion'],'Same original question?')
        prepared=self.root/'naver_blog_posting/output/acc/prepared'
        options={}
        def prepare(*args,**kwargs):
            self.assertEqual(options['topic_seed'],'Same original question?')
            self.assertFalse(kwargs['publication_attempt'])
            return None,prepared,None,None,None,None
        runner=SimpleNamespace(RUN_OPTIONS=options,pipeline_lock=lambda:nullcontext(),
            collect_evidence=lambda account,query:{'account':account,'query':query,'competitors':[]},prepare_content=prepare)
        row={'status':'processing','step':'acquire','plan':{'workTarget':target}}
        with patch.object(autonomy,'ROOT',self.root), \
                patch.object(repair_workflow,'_recovery_row',return_value=(None,row)), \
                patch.object(repair_workflow,'_recovery_resume_guard'), \
                patch.object(naver_blog_posting,'pipeline_runner',runner,create=True):
            self.assertEqual(autonomy.acquire_bound_work('task','digest')['status'],'prepared')
            with self.assertRaises(ValueError):autonomy.acquire_bound_work('task','digest')
        self.assertEqual(original.read_bytes(),before)
        result=json.loads((folder/'original-work-preparation.json').read_bytes())
        self.assertFalse(result['publicationAttempted'])
        self.assertEqual(result['workId'],'original-work')

    def test_reservation_or_unknown_body_cannot_become_public_knowledge(self):
        from common.hermes_memory import write_verified_work_receipt
        saved=self.save('saved.json',{'document':{'components':[]}})
        expected={'account':'acc','title':'Original title','reserveTime':'2026-10-22 19:00',
            'documentSha256':'a'*64,'savedDocumentPath':str(saved),
            'savedDocumentSha256':hashlib.sha256(saved.read_bytes()).hexdigest()}
        reservation=self.save('reservation.json',{**expected,'blogId':'originalblog','submissionStatus':'verified_reserved'})
        observation={**expected,'publicUrl':'https://blog.naver.com/originalblog/123',
            'publicPublicationVerified':True,'publicHttpStatus':200,'publicBodyMatched':True,
            'bodyParagraphsMatch':True,'publicBodySha256':'b'*64}
        for index,change in enumerate(({'publicBodyMatched':None},{'publicPublicationVerified':False},
                                      {'publicUrl':'https://blog.naver.com/otherblog/123'},{})):
            with self.subTest(change=change):
                proof=self.save('completion.json',{'type':'naver_public_completion_v1',
                    'expected':expected,'observation':{**observation,**change}})
                paths=[saved,reservation,proof]
                def write_receipt():
                    return write_verified_work_receipt(self.root/f'work-{index}.json',
                        work_type='verified_work_receipt_v1',channel='naver_blog',outcome='public_naver_verified',
                        scope='public_naver_verified',source_agent='publi',evidence_text='Actual original public work verified.',
                        artifacts=[{'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in paths],
                        checks=[{'type':kind,'passed':True,'evidenceRef':str(proof)} for kind in ('public_identity','public_content')])
                if change:
                    with self.assertRaises(ValueError):write_receipt()
                else:self.assertTrue(write_receipt()['sourceSha256'])

    def test_failed_work_stays_claimed_without_enqueuing_new_cycle(self):
        from server import agent_tools, project_monitor
        queue = self.root/'queue';queue.mkdir()
        config = self.save('config.json', {'enabled':True,'projects':['cf_blog']})
        schedule = self.save('cf_posting/data/daily_schedule.json', {'date':'2026-10-22','items':[
            {'domain':'original.example','status':'review_required','lastError':'Missing original evidence','order':1}]})
        request_id = 'original-request'
        request = {'requestId':request_id,'taskId':'staff:original','status':'completed','actions':[]}
        (queue/(hashlib.sha256(request_id.encode()).hexdigest()+'.json')).write_text(json.dumps(request))
        state = self.save('state.json', {'projects':{'cf_blog':{'requestId':request_id,'observedRequestId':request_id}}})
        with patch.object(autonomy,'ROOT',self.root), patch.object(autonomy,'STATE',state), \
                patch.object(autonomy,'CONFIG',config), patch.object(agent_tools,'STAFF_REQUEST_DIR',queue), \
                patch.object(agent_tools,'enqueue_staff_request') as enqueue, \
                patch.object(project_monitor,'INCIDENTS',self.root/'incidents'), \
                patch('server.project_health.observed_projects',return_value=[{'id':'cf_blog','status':'attention'}]):
            self.assertFalse(autonomy.process_project_autonomy_once())
            original = json.loads(state.read_bytes())['projects']['cf_blog']['failureWork']
            self.save('cf_posting/data/daily_schedule.json', {'date':'2026-10-23','items':[
                {'domain':'new.example','status':'failed','lastError':'new failure','order':0}]})
            self.assertFalse(autonomy.process_project_autonomy_once())
            current = json.loads(state.read_bytes())['projects']['cf_blog']['failureWork']
            self.assertEqual(current['workId'], original['workId'])
            self.assertEqual(current['target']['identity'], 'original.example')
            enqueue.assert_not_called()


if __name__ == '__main__':
    unittest.main()
