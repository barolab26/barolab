import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from common import repair_workflow as repair


class ProjectRecoveryTests(unittest.TestCase):
    """All models, crew events and operations are isolated from live workers."""
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.patchers=[patch.object(repair,'ROOT',self.root/'ledger'),
            patch('common.crew_chat_bridge.emit_work_event',return_value='test-event')]
        for item in self.patchers:item.start()
        self.addCleanup(self.temp.cleanup)
        for item in self.patchers:self.addCleanup(item.stop)
        self.source=self.root/'source.json';self.source.write_text('{"items":[]}')
        self.request=self.root/'request.json';self.request.write_text('{"status":"failed","results":[]}')
        self.plan={'sourcePath':str(self.source),'originalRequestPath':str(self.request),
            'originalRequestSha256':repair._sha(self.request.read_bytes()),
            'projectRoot':str(self.root),'failure':[],
            'action':{'agent':'publi','tool':'prepare_cf_source_fact','args':{}},
            'sourceSnapshot':{'lastError':'Observed error'}}
        self.digest=repair._sha(json.dumps(self.plan,sort_keys=True,ensure_ascii=False).encode())
        self.path=repair._recovery_path('incident-1')
        self.path.parent.mkdir(parents=True)
        self.row={'type':'project_recovery_v1','taskId':'incident-1','plan':self.plan,
            'planSha256':self.digest,'step':'discover','status':'ready','steps':{},'resumeAttempted':False}
        repair.write(self.path,self.row)

    def call(self,actor):
        return repair.advance_project_recovery('incident-1',self.digest,actor=actor)

    def set_step(self,step,**extra):
        row=json.loads(self.path.read_bytes());row.update(step=step,status='ready',**extra)
        repair.write(self.path,row)

    def test_exact_actor_plan_and_single_phase_claim(self):
        with self.assertRaises(ValueError):self.call('jarvis')
        with self.assertRaises(ValueError):repair.advance_project_recovery('incident-1','0'*64,actor='patch')
        with patch.object(repair,'_discover_recovery',return_value={'files':[],'testFiles':[]}) as discover:
            self.assertEqual(self.call('patch')['nextStep'],'classify')
            with self.assertRaises(ValueError):self.call('patch')
            discover.assert_called_once()

    def test_sandbox_and_final_review_are_required_before_apply(self):
        self.set_step('test',job={'jobDir':'fixture','candidateSha256':'a'},review={'reviewSha256':'pre'})
        with patch('common.coding_job.validate_coding_job',return_value={'status':'isolated_verified','sandbox':{'enforced':False}}) as validate:
            self.assertEqual(self.call('doctor')['recoveryStatus'],'held')
            self.assertEqual(validate.call_args.kwargs,{'sandbox':True,'review_sha256':'pre'})
        self.assertFalse(json.loads(self.path.read_bytes())['resumeAttempted'])

    def test_unknown_submission_does_not_resume_or_learn(self):
        self.source.write_text('{"items":[{"status":"unknown","submittedAt":"actual-time"}]}')
        self.set_step('resume')
        with patch('common.ego_executor.execute_staff_action') as execute,patch('common.llm_client.record_verified_work') as learn:
            self.assertEqual(self.call('publi')['recoveryStatus'],'held')
            execute.assert_not_called();learn.assert_not_called()

    def test_returned_operation_without_verified_proof_never_learns(self):
        self.set_step('resume')
        with patch('common.ego_executor.execute_staff_action',return_value={'ok':True,'status':'completed'}) as execute:
            self.assertEqual(self.call('publi')['nextStep'],'verify')
            execute.assert_called_once()
        with patch('common.llm_client.record_verified_work') as learn:
            self.assertEqual(self.call('jarvis')['recoveryStatus'],'awaiting_verified_work')
            learn.assert_not_called()
        with self.assertRaises(ValueError):self.call('publi')

    def test_changed_original_request_blocks_resume(self):
        self.set_step('resume');self.request.write_text('{"status":"completed"}')
        with patch('common.ego_executor.execute_staff_action') as execute:
            self.assertEqual(self.call('publi')['recoveryStatus'],'held')
            execute.assert_not_called()

    def test_busy_mutation_preserves_candidate_without_consuming_phase(self):
        from contextlib import contextmanager
        @contextmanager
        def busy(_):
            raise repair.RecoveryBusy('busy')
            yield
        self.set_step('apply',job={'candidateSha256':'same-candidate'})
        with patch.object(repair,'_recovery_mutation_locks',busy),patch('common.coding_job.apply_coding_job') as apply:
            result=self.call('patch')
            apply.assert_not_called()
        row=json.loads(self.path.read_bytes())
        self.assertEqual(result['recoveryStatus'],'ready')
        self.assertEqual(row['job']['candidateSha256'],'same-candidate')
        self.assertNotIn('apply',row['steps'])
        self.assertFalse(row['resumeAttempted'])

    def test_unknown_project_cannot_gain_registered_mutation_lock(self):
        self.row['plan']['project']='mobile_apps'
        self.row['discovered']={'files':['apps/example.py']}
        with self.assertRaises(ValueError), repair._recovery_mutation_locks(self.row):
            pass

    def test_original_execution_lookup_uses_immutable_snapshot_and_exact_action(self):
        from server import agent_tools
        staff=self.root/'staff';staff.mkdir()
        receipts=self.root/'processes';folder=receipts/'actual-host-id';folder.mkdir(parents=True)
        action={'agent':'publi','tool':'run_cf_domain','args':{'domain':'soulnote.kr',
            'source_sha256':'a'*64,'artifact_sha256':'b'*64,'review_sha256':'c'*64}}
        original={'requestId':'original','taskId':'staff:original','status':'processing','actions':[action]}
        snapshot=folder/'request.json';snapshot.write_text(json.dumps(original))
        snapshot_sha=repair._sha(snapshot.read_bytes())
        original['status']='failed'
        current=staff/(repair._sha(b'original')+'.json');current.write_text(json.dumps(original))
        inspected=staff/'inspection.json';inspected.write_text(json.dumps({'actions':[{'agent':'patch','tool':'read_agent_status','args':{}}]}))
        receipt={'status':'failed','action':{**action,'argumentsComplete':True},
            'context':{'taskId':'staff:original'},'originalTaskRef':{'requestId':'original','taskId':'staff:original','requestSha256':snapshot_sha}}
        (folder/'receipt.json').write_text(json.dumps(receipt))
        incident={'observation':{'failures':[{'identity':'soulnote.kr'}]}}
        with patch.object(agent_tools,'EGO_PROCESS_DIR',receipts),patch.object(agent_tools,'STAFF_REQUEST_DIR',staff):
            selected,evidence=repair._original_recovery_request(incident,inspected)
            self.assertEqual(selected,current)
            self.assertEqual(evidence['originalTaskRef']['requestSha256'],snapshot_sha)
            snapshot.write_text('{"changed":true}')
            self.assertEqual(repair._original_recovery_request(incident,inspected),(inspected,None))

    def test_dispatch_phase_request_is_idempotent_and_uses_expected_staff(self):
        with patch('server.agent_tools.enqueue_staff_request',return_value={'requestId':'queued'}) as enqueue:
            self.assertTrue(repair.dispatch_project_recovery_once())
            self.assertFalse(repair.dispatch_project_recovery_once())
            self.assertEqual(enqueue.call_args.args[1],[{'agent':'patch','tool':'advance_project_recovery',
                'args':{'task_id':'incident-1','plan_sha256':self.digest}}])

    def test_running_child_is_observed_until_terminal_without_reexecution(self):
        from server import agent_tools
        directory=self.root/'processes';folder=directory/'actual-child';folder.mkdir(parents=True)
        receipt={'status':'running','pid':123,'startedAt':'actual-start',
            'context':{'taskId':'incident-1','requestId':'recovery:'+self.digest},
            'action':{**self.plan['action'],'argumentsComplete':True}}
        receipt_path=folder/'receipt.json';receipt_path.write_text(json.dumps(receipt))
        self.set_step('resume')
        with patch.object(agent_tools,'EGO_PROCESS_DIR',directory),patch('common.ego_executor.execute_staff_action',return_value={'ok':True,'status':'running','receiptPath':str(receipt_path)}) as execute:
            self.assertEqual(self.call('publi')['recoveryStatus'],'awaiting_completion')
            receipt.update(status='exited',exitCode=0,finishedAt='actual-end');receipt_path.write_text(json.dumps(receipt))
            self.assertTrue(repair.dispatch_project_recovery_once())
            row=json.loads(self.path.read_bytes())
            self.assertEqual((row['status'],row['step']),('ready','verify'))
            self.assertTrue(row['resumeAttempted']);execute.assert_called_once()
        with patch('common.llm_client.record_verified_work') as learn:
            self.assertEqual(self.call('jarvis')['recoveryStatus'],'awaiting_verified_work')
            learn.assert_not_called()

    def test_actual_rejection_allows_one_new_candidate_not_business_retry(self):
        job=self.root/'job';job.mkdir()
        rejection={'route':{'state':'returned'},'verdict':{'scopeRespected':False,'reason':'Unrelated change'}}
        (job/'review.json').write_text(json.dumps(rejection))
        self.set_step('review',job={'jobDir':str(job),'candidateSha256':'candidate'})
        with patch('common.coding_job.review_coding_job',side_effect=ValueError('rejected')):
            result=self.call('jarvis')
            self.assertEqual(result['nextStep'],'propose')
            row=json.loads(self.path.read_bytes())
            self.assertEqual(row['candidateRevision'],2);self.assertFalse(row['resumeAttempted'])
            self.set_step('review')
            self.assertEqual(self.call('jarvis')['recoveryStatus'],'held')

    def test_original_work_lookup_never_selects_another_or_older_success(self):
        from common.hermes_memory import write_verified_work_receipt
        folder=self.root/'cf_posting/output/exact-slug/run';folder.mkdir(parents=True)
        publication=folder/'publication.json';validation=folder/'validation.json'
        publication.write_text(json.dumps({'status':'verified','postId':9,'publicUrl':'https://example.com/exact-slug'}))
        validation.write_text(json.dumps({'publication':'verified','postId':9,'publicUrl':'https://example.com/exact-slug','verifiedAt':'actual-time'}))
        proof=write_verified_work_receipt(folder/'work-learning-receipt.json',work_type='verified_work_receipt_v1',
            channel='cf_blog',outcome='public_verified',scope='public_verified',source_agent='publi',
            evidence_text='Exact original article identity and public content verified.',
            artifacts=[{'path':str(p),'sha256':repair._sha(p.read_bytes())} for p in (publication,validation)],
            checks=[{'type':k,'passed':True,'evidenceRef':str(p)} for k,p in [('public_identity',publication),('public_content',validation)]])
        row={'plan':{'project':'cf_blog','projectRoot':str(self.root),'action':{'args':{'domain':'example.com'}},
            'sourceSnapshot':{'items':[{'domain':'example.com','slug':'exact-slug','artifactFolder':'output/exact-slug/run'}]}},
            'steps':{'resume':{'startedAt':0}}}
        self.assertEqual(repair._find_recovery_work(row),proof)
        row['steps']['resume']['startedAt']=repair.time.time()+1
        self.assertIsNone(repair._find_recovery_work(row))
        row['steps']['resume']['startedAt']=0
        row['plan']['sourceSnapshot']['items'][0]['slug']='another-slug'
        with self.assertRaises(ValueError):repair._find_recovery_work(row)

    def test_discovery_binds_real_import_context_and_policy_without_model_paths(self):
        (self.root/'main.py').write_text('import dependency\nPOLICY="policy.md"\n')
        (self.root/'dependency.py').write_text('VALUE=1\n')
        (self.root/'policy.md').write_text('Keep actual factual checks.\n')
        (self.root/'test_main.py').write_text('import main\nimport unittest\n')
        self.row['plan']['sourceSnapshot']={'lastError':'Traceback (most recent call last):\n  File "'+str(self.root/'main.py')+'", line 1\nValueError: actual failure'}
        found=repair._discover_recovery(self.row)
        self.assertEqual(found['files'],['main.py'])
        self.assertEqual(found['testFiles'],['test_main.py'])
        self.assertIn('dependency.py',found['contextFiles'])
        self.assertIn('policy.md',found['policyFiles'])
        self.assertEqual(found['fileHashes']['dependency.py'],repair._sha((self.root/'dependency.py').read_bytes()))


class RepairWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.path=self.root/'proof.json'
        self.proof={'failureType':repair.KNOWN_FAILURE,'taskId':'job1','submissionStarted':False,'status':'failed'}
        self.path.write_text(json.dumps(self.proof));self.sha=hashlib.sha256(self.path.read_bytes()).hexdigest()
        evidence=self.root/'validated.json';evidence.write_text(json.dumps({'taskId':'job1','testsPassed':True,'repairRevision':'fixed-source-sha'}))
        self.handler=Mock(return_value={'status':'validated','testsPassed':True,'repairRevision':'fixed-source-sha',
            'evidencePath':str(evidence),'evidenceSha256':hashlib.sha256(evidence.read_bytes()).hexdigest()})
        self.resume=Mock(return_value={'status':'held'})
        self.verdict={**{key:True for key in ('supported','gatesPreserved','sameTask','safeToResume')},'contract':'guarded-attempt-v1','reason':'Host evidence supports this bounded repair','missingEvidence':[]}
        def generate(prompt,**kwargs):
            self.last_prompt=prompt
            kwargs['observer'](kwargs['provider'],kwargs['model_override'],'calling')
            kwargs['observer'](kwargs['provider'],kwargs['model_override'],'returned',actual_model='actual-configured-model')
            return self.verdict
        self.patches=[patch.object(repair,'ROOT',self.root/'ledger'),patch('common.crew_chat_bridge.emit_work_event',return_value='request-event'),
                      patch('common.llm_client.generate_json',side_effect=generate),
                      patch('common.llm_settings.get_agent_brain',return_value={'provider':'codex','model':'configured-jarvis-model'})]
        for p in self.patches:p.start()
    def tearDown(self):
        for p in reversed(self.patches):p.stop()
        self.temp.cleanup()
    def run_job(self):
        return repair.run_known_repair('job1',self.path,self.sha,handler=self.handler,resume=self.resume)
    def test_review_then_single_resume_without_attempt_reset(self):
        result=self.run_job();self.assertEqual(result['status'],'resume_held')
        args=self.resume.call_args.args
        permit=Path(args[2]['resumePermitPath'])
        self.assertEqual(hashlib.sha256(permit.read_bytes()).hexdigest(),args[2]['resumePermitSha256'])
        self.run_job();self.handler.assert_called_once();self.resume.assert_called_once()
    def test_actual_stage_evidence_is_required_for_verified_resume(self):
        artifact=self.root/'keywords.md';artifact.write_text('# Accepted keyword\nEvidence-backed candidate\n')
        evidence=self.root/'resume.json'
        evidence.write_text(json.dumps({'taskId':'job1','failureType':repair.KNOWN_FAILURE,'failureStagePassed':True,
            'sourceArtifacts':[{'path':str(artifact),'sha256':hashlib.sha256(artifact.read_bytes()).hexdigest()}]}))
        self.resume.return_value={'returncode':0,'evidencePath':str(evidence),'evidenceSha256':hashlib.sha256(evidence.read_bytes()).hexdigest()}
        self.assertEqual(self.run_job()['status'],'resume_verified')

    def test_verified_markdown_stage_preserves_later_review_hold(self):
        artifact=self.root/'keywords.md';artifact.write_text('# Accepted keyword')
        evidence=self.root/'resume.json'
        evidence.write_text(json.dumps({'taskId':'job1','failureType':repair.KNOWN_FAILURE,'failureStagePassed':True,
            'sourceArtifacts':[{'path':str(artifact),'sha256':hashlib.sha256(artifact.read_bytes()).hexdigest()}]}))
        self.resume.return_value={'status':'review_required','currentStage':5,'returncode':1,
            'evidencePath':str(evidence),'evidenceSha256':hashlib.sha256(evidence.read_bytes()).hexdigest()}
        with patch('common.crew_chat_bridge.emit_work_event',return_value='request-event') as emit:
            result=self.run_job()
        self.assertEqual(result['status'],'resume_held')
        self.assertTrue(result['failureStageVerified'])
        self.assertIn('runner=review_required; stage=5; exit=1',emit.call_args.kwargs['output_kind'])

    def test_changed_markdown_stage_evidence_never_verifies_resume(self):
        artifact=self.root/'keywords.md';artifact.write_text('# Original approved candidate')
        original_sha=hashlib.sha256(artifact.read_bytes()).hexdigest()
        artifact.write_text('# Changed candidate')
        evidence=self.root/'resume.json'
        evidence.write_text(json.dumps({'taskId':'job1','failureType':repair.KNOWN_FAILURE,'failureStagePassed':True,
            'sourceArtifacts':[{'path':str(artifact),'sha256':original_sha}]}))
        self.resume.return_value={'returncode':0,'evidencePath':str(evidence),'evidenceSha256':hashlib.sha256(evidence.read_bytes()).hexdigest()}
        result=self.run_job()
        self.assertEqual(result['status'],'hold')
        self.assertTrue(result['resumeAttempted'])
        self.run_job();self.resume.assert_called_once()

    def test_material_review_continuation_preserves_rejection_and_shared_budget(self):
        self.verdict['supported']=False
        old=self.run_job()
        old_path=repair.ROOT/(old['fingerprint']+'.json');old_bytes=old_path.read_bytes()
        evidence=Path(self.handler.return_value['evidencePath'])
        actual=json.loads(evidence.read_text());actual['newEvidence']='Host integration regression and callsite proof'
        evidence.write_text(json.dumps(actual));new_sha=hashlib.sha256(evidence.read_bytes()).hexdigest()
        self.handler.return_value['evidenceSha256']=new_sha
        approval=self.root/'approval.json'
        value={'taskId':'job1','approved':True,'reviewRevision':'review-v2',
               'oldReviewSha256':hashlib.sha256(old_bytes).hexdigest(),'newRepairEvidenceSha256':new_sha}
        approval.write_text(json.dumps(value));approval_sha=hashlib.sha256(approval.read_bytes()).hexdigest()
        self.verdict['supported']=True
        result=repair.run_known_repair('job1',self.path,self.sha,handler=self.handler,resume=self.resume,
             review_approval_path=approval,review_approval_sha256=approval_sha)
        self.assertEqual(result['status'],'resume_held')
        self.assertEqual(old_path.read_bytes(),old_bytes)
        self.assertNotEqual(result['fingerprint'],old['fingerprint'])
        repair.run_known_repair('job1',self.path,self.sha,handler=self.handler,resume=self.resume,
             review_approval_path=approval,review_approval_sha256=approval_sha)
        self.resume.assert_called_once()

    def test_explicit_v3_binds_host_query_and_preserves_v2(self):
        base=repair._sha(('job1|'+repair.KNOWN_FAILURE).encode())
        v2=repair._sha((base+'|review-v2').encode())
        repair.ROOT.mkdir(parents=True)
        old_path=repair.ROOT/(v2+'.json')
        old_path.write_text(json.dumps({'taskId':'job1','status':'review_rejected','resumeAttempted':False,
            'reviewRevision':'review-v2','failureEvidenceSha256':self.sha,'repairEvidenceSha256':'old-evidence'}))
        old_bytes=old_path.read_bytes()
        evidence=Path(self.handler.return_value['evidencePath']);actual=json.loads(evidence.read_text())
        actual['approvedQuery']='수목원 예약'
        for field in ('queryEvidence','intentEvidence'):
            artifact=self.root/(field+'.json');artifact.write_text('{"hostVerified":true}')
            actual[field+'Path']=str(artifact);actual[field+'Sha256']=repair._sha(artifact.read_bytes())
        evidence.write_text(json.dumps(actual));new_sha=repair._sha(evidence.read_bytes())
        self.handler.return_value['evidenceSha256']=new_sha
        approval=self.root/'approval-v3.json';approval.write_text(json.dumps({'taskId':'job1','approved':True,
            'reviewRevision':'review-v3','oldReviewSha256':repair._sha(old_bytes),'newRepairEvidenceSha256':new_sha}))
        result=repair.run_known_repair('job1',self.path,self.sha,handler=self.handler,resume=self.resume,
            review_approval_path=approval,review_approval_sha256=repair._sha(approval.read_bytes()))
        self.assertEqual(result['status'],'resume_held')
        self.assertEqual(old_path.read_bytes(),old_bytes)
        self.assertEqual(result['previousFingerprint'],v2)
        permit=json.loads(Path(self.resume.call_args.args[2]['resumePermitPath']).read_text(encoding='utf-8'))
        self.assertEqual(permit['reviewedInputs']['approvedQuery'],'수목원 예약')
        self.assertIn('verifiedQueryIntentEvidence',self.last_prompt)
        self.assertIn('hostVerified',self.last_prompt)
        self.assertEqual(permit['reviewedInputs']['intentEvidenceSha256'],actual['intentEvidenceSha256'])
        self.assertEqual(result['fingerprint'],repair._sha((base+'|review-v3').encode()))

    def test_actual_generic_diagnosis_runs_once_without_repair_or_resume(self):
        event={'eventId':'failure1','taskId':'other-task','who':'cf-pipeline','phase':'failed','stage':'model','evidenceId':'sha'}
        repair.record_failed_event(event)
        def diagnose(prompt,**kwargs):
            kwargs['observer']('codex','configured-jarvis-model','returned',actual_model='actual-model')
            if kwargs.get('crew_actor')=='jarvis':
                return {'diagnosisSupported':True,'requiredEvidenceAppropriate':True,'handlerSupported':False,'reason':'More host evidence is needed'}
            return {'classification':'needs_evidence','reason':'No exception or source was supplied',
                    'requiredEvidence':['Host exception class and bounded stack location']}
        with patch('common.llm_client.generate_json',side_effect=diagnose) as model:
            self.assertTrue(repair.process_repair_diagnosis_once())
            self.assertFalse(repair.process_repair_diagnosis_once())
            self.assertEqual(model.call_count,2)
        rows=[json.loads(p.read_text(encoding='utf-8')) for p in repair.ROOT.glob('*.json')]
        self.assertEqual(rows[0]['status'],'diagnosed_needs_evidence')
        self.assertEqual(rows[0]['diagnosisRoute']['events'][0]['actualModel'],'actual-model')
        self.resume.assert_not_called();self.handler.assert_not_called()

    def test_v4_cannot_skip_exact_rejected_v3(self):
        base=repair._sha(('job1|'+repair.KNOWN_FAILURE).encode())
        v3=repair._sha((base+'|review-v3').encode())
        repair.ROOT.mkdir(parents=True)
        old=repair.ROOT/(v3+'.json')
        old.write_text(json.dumps({'taskId':'job1','status':'review_rejected','resumeAttempted':False,
            'reviewRevision':'review-v2','failureEvidenceSha256':self.sha,'repairEvidenceSha256':'old'}))
        approval=self.root/'v4.json';approval.write_text(json.dumps({'taskId':'job1','approved':True,
            'reviewRevision':'review-v4','oldReviewSha256':repair._sha(old.read_bytes()),'newRepairEvidenceSha256':'new'}))
        with self.assertRaises(ValueError):
            repair.run_known_repair('job1',self.path,self.sha,handler=self.handler,resume=self.resume,
                review_approval_path=approval,review_approval_sha256=repair._sha(approval.read_bytes()))
        self.handler.assert_not_called();self.resume.assert_not_called()

    def test_diagnosis_request_id_is_persisted_for_actual_reply_parent(self):
        event={'eventId':'original-failure','taskId':'request-task','who':'cf-pipeline','phase':'failed','stage':'model','evidenceId':'sha'}
        row=repair.record_failed_event(event)
        self.assertEqual(row['diagnosisRequestId'],'request-event')
        stored=json.loads((repair.ROOT/(row['fingerprint']+'.json')).read_text())
        self.assertEqual(stored['diagnosisRequestId'],'request-event')
        self.assertEqual(stored['sourceEventId'],'original-failure')

    def test_stale_diagnosis_is_held_without_automatic_retry(self):
        repair.ROOT.mkdir(parents=True)
        path=repair.ROOT/'stale.json';path.write_text(json.dumps({'status':'diagnosing','diagnosisStartedAt':0}))
        with patch('common.llm_client.generate_json') as model:
            self.assertFalse(repair.process_repair_diagnosis_once())
            model.assert_not_called()
        self.assertEqual(json.loads(path.read_text())['status'],'diagnosis_hold')

    def test_same_evidence_review_continuation_is_rejected(self):
        self.verdict['supported']=False;old=self.run_job()
        old_path=repair.ROOT/(old['fingerprint']+'.json')
        approval=self.root/'approval.json'
        approval.write_text(json.dumps({'taskId':'job1','approved':True,'reviewRevision':'review-v2',
            'oldReviewSha256':hashlib.sha256(old_path.read_bytes()).hexdigest(),
            'newRepairEvidenceSha256':old['repairEvidenceSha256']}))
        with self.assertRaises(ValueError):
            repair.run_known_repair('job1',self.path,self.sha,handler=self.handler,resume=self.resume,
                review_approval_path=approval,review_approval_sha256=hashlib.sha256(approval.read_bytes()).hexdigest())
        self.resume.assert_not_called()

    def test_missing_review_reason_holds_without_resume(self):
        del self.verdict['reason']
        self.assertEqual(self.run_job()['status'],'hold')
        self.resume.assert_not_called()

    def test_jarvis_configured_route_and_actual_model_are_recorded(self):
        result=self.run_job()
        route=result['reviewRoute']
        self.assertEqual(route['configuredProvider'],'codex')
        self.assertEqual(route['configuredModel'],'configured-jarvis-model')
        self.assertEqual(route['events'][-1]['actualModel'],'actual-configured-model')
        self.assertEqual(route['events'][-1]['provider'],'codex')

    def test_prohibited_jarvis_route_never_calls_model_or_resume(self):
        with patch('common.llm_settings.get_agent_brain',return_value={'provider':'freellmapi','model':'any'}), patch('common.llm_client.generate_json') as model:
            result=self.run_job()
        self.assertEqual(result['status'],'hold')
        model.assert_not_called();self.resume.assert_not_called()

    def test_independent_reject_never_resumes(self):
        self.verdict['safeToResume']=False
        self.assertEqual(self.run_job()['status'],'review_rejected');self.resume.assert_not_called()
    def test_unknown_submission_and_changed_evidence_rejected(self):
        self.proof['submissionStarted']=True;self.path.write_text(json.dumps(self.proof))
        self.sha=hashlib.sha256(self.path.read_bytes()).hexdigest()
        with self.assertRaises(ValueError):self.run_job()
        self.handler.assert_not_called()
    def test_crash_after_resume_is_held_without_second_attempt(self):
        self.resume.side_effect=RuntimeError('private')
        result=self.run_job();self.assertEqual(result['status'],'hold');self.assertTrue(result['resumeAttempted'])
        self.run_job();self.resume.assert_called_once()
    def test_generic_intake_deduplicates_without_handler_or_recursive_repair(self):
        event={'eventId':'event1','taskId':'model1','who':'common-runner','phase':'failed','stage':'model','evidenceId':'proof'}
        first=repair.record_failed_event(event);second=repair.record_failed_event(event)
        self.assertEqual(first,second);self.assertEqual(first['status'],'needs_diagnosis')
        self.assertIsNotNone(repair.record_failed_event({**event,'who':'patch','taskId':'patch-own-task'}))
        token=repair._active.set(True)
        try:self.assertIsNone(repair.record_failed_event(event))
        finally:repair._active.reset(token)
        self.handler.assert_not_called()

# Plain unittest runs must never publish fixture events or diagnose them in production.
def setUpModule():
    import tempfile
    from pathlib import Path
    from unittest.mock import patch
    from common import repair_workflow
    global _isolated_crew_temp, _isolated_crew_patches
    _isolated_crew_temp = tempfile.TemporaryDirectory()
    root = Path(_isolated_crew_temp.name)
    _isolated_crew_patches = [
        patch('common.crew_chat_bridge._deliver', return_value=True),
        patch('common.crew_chat_bridge.OUTBOX_DIR', root / 'outbox'),
        patch.object(repair_workflow, 'ROOT', root / 'repairs'),
    ]
    for guard in _isolated_crew_patches:
        guard.start()


def tearDownModule():
    for guard in reversed(_isolated_crew_patches):
        guard.stop()
    _isolated_crew_temp.cleanup()


if __name__=='__main__':unittest.main()
