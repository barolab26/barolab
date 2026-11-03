"""Isolated recovery admission, durable retry and CEO request regression checks."""
import copy
import hashlib
import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from common import repair_workflow as recovery, crew_chat_bridge as bridge, llm_usage
from common import work_agenda as agendas
from common.collection_observability import write, load
from server import agent_tools


class RecoveryControls(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.repairs=self.root/'repairs'
        self.requests=self.root/'staff'
        self.requests.mkdir()
        for target,name,value in ((recovery,'ROOT',self.repairs),(llm_usage,'ROOT',self.root),
                                  (agent_tools,'STAFF_REQUEST_DIR',self.requests),
                                  (agent_tools,'BASE_DIR',self.root)):
            patcher=patch.object(target,name,value);patcher.start();self.addCleanup(patcher.stop)
        for name in ('_deliver','emit_work_event'):
            patcher=patch.object(bridge,name,return_value='event');patcher.start();self.addCleanup(patcher.stop)
        self.agenda={'id':'agenda-one','project':'threads'}

    def make_row(self,**changes):
        plan={'project':'threads','failure':[{'error':'internal parse failed'}],
              'action':{'agent':'publi','tool':'retry_conference','args':{}},'sourceSnapshot':{}}
        digest=hashlib.sha256(json.dumps(plan,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        row={'type':'project_recovery_v1','taskId':'incident-one','plan':plan,'planSha256':digest,
             'step':'classify','status':'ready','steps':{},'businessAgendaId':self.agenda['id'],
             'resumeAttempted':False,'discovered':{'errors':'internal parse failed','files':['worker.py'],
                 'fileHashes':{'worker.py':'hash-one'},'environment':{'browserWindow':{'status':'available','browserPid':1}}}}
        row.update(changes)
        path=recovery._recovery_path(row['taskId']);write(path,row)
        return path,row

    def budget(self):
        data=self.root/'dashboard/data'
        write(data/'publication-conferences/operations/agenda-one.json',{'businessExperiment':{'maxModelCalls':20}})
        write(data/'llm_usage_ledger.json',{'byAgenda':{'agenda-one':{'modelCalls':447}}})

    def test_budget_repeated_cycles_restart_never_dispatch_or_classify(self):
        self.budget();path,row=self.make_row()
        with patch.object(agendas,'enabled',return_value=True),patch.object(agendas,'active_ids',return_value=['agenda-one']), \
             patch.object(agendas,'get',return_value=self.agenda),patch.object(agent_tools,'enqueue_staff_request') as queue, \
             patch.object(recovery,'_discover_recovery') as discover:
            for _ in range(4):self.assertFalse(recovery.dispatch_project_recovery_once())
            # Each call reloads the durable file; no in-memory counter enables a restart.
            saved=load(path)
            self.assertEqual(saved['retryBarrier']['reasonCode'],'budget_exhausted')
            self.assertEqual(len(saved['barrierHistory']),1)
            self.assertEqual(saved['steps'],{})
            queue.assert_not_called();discover.assert_not_called()
        with patch.object(agendas,'enabled',return_value=True),patch.object(agendas,'require',return_value=self.agenda), \
             patch.object(recovery,'_classify_recovery') as classify:
            result=recovery.advance_project_recovery(row['taskId'],row['planSha256'],actor='jarvis')
            self.assertEqual(result['status'],'held');classify.assert_not_called()

    def test_protected_causes_never_reopen_when_unrelated_evidence_changes(self):
        for error,cause in [('manual_stop','manual_stop'),('AuthenticationError','authentication_required'),
                            ('Configured Jarvis route unavailable','configuration_required'),('pending_effect unknown','uncertain_effect')]:
            with self.subTest(error=error):
                path,row=self.make_row(status='held',errorCode='classify:ValueError',holdReason=error)
                with patch.object(agendas,'enabled',return_value=False),patch.object(recovery,'_discover_recovery') as discover, \
                     patch.object(agent_tools,'enqueue_staff_request') as queue:
                    recovery.dispatch_project_recovery_once()
                    self.assertEqual(load(path)['retryBarrier']['reasonCode'],cause)
                    discover.assert_not_called();queue.assert_not_called()

    def test_null_errors_are_not_failures(self):
        self.assertEqual(recovery._failure_cause({'error':None,'lastError':None,'result':{'error':None,'status':'completed'}}),'')
        _,row=self.make_row();row['plan']['failure']=[{'error':None}]
        self.assertEqual(recovery.recovery_blocker(row),'')

    def test_normal_configuration_and_unknown_measurement_are_not_submission_failures(self):
        for value in ({'status':'configured'}, {'configuration':{'status':'configured'}},
                      {'metrics':{'status':'unknown','value':None}}, {'error':None,'measurement':{'status':'unknown'}}):
            self.assertEqual(recovery._failure_cause(value),'')
        self.assertEqual(recovery._failure_cause({'submissionStarted':True,'status':'unknown'}),'uncertain_effect')
        self.assertEqual(recovery._failure_cause({'submissionStatus':'unknown'}),'uncertain_effect')

    def test_settled_submission_requires_valid_receipt_bound_to_exact_public_target(self):
        from common.hermes_memory import write_verified_work_receipt
        artifact=self.root/'public.json'
        write(artifact,{'postId':'post-one','publicUrl':'https://example.test/one',
                        'status':'verified','publication':'verified','verifiedAt':'2026-11-03T10:00:00Z'})
        proof=write_verified_work_receipt(self.root/'proof.json',work_type='verified_work_receipt_v1',
            channel='cf_blog',outcome='public_verified',scope='public_verified',source_agent='publi',
            evidence_text='Exact original public identity and content matched.',
            artifacts=[{'path':str(artifact),'sha256':hashlib.sha256(artifact.read_bytes()).hexdigest()}],
            checks=[{'type':kind,'passed':True,'evidenceRef':str(artifact)} for kind in ('public_identity','public_content')])
        item={'submissionStarted':True,'status':'completed','postId':'post-one','publicUrl':'https://example.test/one',
              'verifiedWorkProof':proof}
        self.assertEqual(recovery._failure_cause(item),'')
        self.assertEqual(recovery._failure_cause({**item,'postId':'other'}),'uncertain_effect')
        write(artifact,{'postId':'changed'})
        self.assertEqual(recovery._failure_cause(item),'uncertain_effect')

    def test_host_resume_corrected_auth_and_config_preserves_history_and_cannot_bypass_budget(self):
        for reason in ('auth_required','invalid_config'):
            with self.subTest(reason=reason):
                source=self.root/'original.json';write(source,{'status':'failed','arguments':{'account':'one'}})
                path,row=self.make_row(status='held',holdReason=reason)
                row['plan'].update(sourcePath=str(source),originalTaskId='conference:original',failure=[{'error':reason}])
                row['planSha256']=hashlib.sha256(json.dumps(row['plan'],sort_keys=True,ensure_ascii=False).encode()).hexdigest()
                write(path,row)
                with patch.object(agendas,'require',return_value=self.agenda),patch.object(recovery,'_recovery_resume_guard'):
                    result=recovery.resume_held_recovery(row['taskId'],row['planSha256'],authorization_id='ceo-response-one')
                    self.assertEqual(result['originalTaskId'],'conference:original')
                    self.assertEqual(recovery.recovery_blocker(load(path),self.agenda),'')
                    self.assertEqual(load(path)['authorizationHistory'][0]['holdReason'],reason)
                    self.assertTrue(recovery.resume_held_recovery(row['taskId'],row['planSha256'],authorization_id='ceo-response-one')['duplicateAuthorization'])
                    write(source,{'status':'unknown'})
                    self.assertEqual(recovery.recovery_blocker(load(path),self.agenda),'authorized_source_changed')
                    self.budget()
                    self.assertEqual(recovery.recovery_blocker(load(path),self.agenda),'budget_exhausted')
                    with self.assertRaisesRegex(ValueError,'budget'):
                        recovery.resume_held_recovery(row['taskId'],row['planSha256'],authorization_id='another-response')
                (self.root/'dashboard/data/llm_usage_ledger.json').unlink()

    def test_host_resume_cannot_bypass_native_unsafe_source_or_replay_submission(self):
        path,row=self.make_row(status='held')
        with patch.object(agendas,'require',return_value=self.agenda), \
             patch.object(recovery,'_recovery_resume_guard',side_effect=ValueError('Original submission requires reconciliation')):
            with self.assertRaisesRegex(ValueError,'reconciliation'):
                recovery.resume_held_recovery(row['taskId'],row['planSha256'],authorization_id='explicit-answer')
        row['resumeAttempted']=True;write(path,row)
        with patch.object(agendas,'require',return_value=self.agenda),patch.object(recovery,'_recovery_resume_guard'):
            with self.assertRaisesRegex(ValueError,'attempted'):
                recovery.resume_held_recovery(row['taskId'],row['planSha256'],authorization_id='explicit-answer')

    def test_explicit_authorization_is_consumed_on_failure_not_an_endless_resume_flag(self):
        source=self.root/'original.json';write(source,{'status':'failed'})
        path,row=self.make_row(status='held',holdReason='auth_required')
        row['plan'].update(sourcePath=str(source),originalTaskId='conference:original',failure=[{'error':'auth_required'}])
        row['planSha256']=hashlib.sha256(json.dumps(row['plan'],sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        write(path,row)
        with patch.object(agendas,'enabled',return_value=True),patch.object(agendas,'require',return_value=self.agenda), \
             patch.object(recovery,'_recovery_resume_guard'),patch.object(recovery,'_discover_recovery',return_value=row['discovered']), \
             patch.object(recovery,'_classify_recovery',side_effect=RuntimeError('auth_required')) as classify:
            recovery.resume_held_recovery(row['taskId'],row['planSha256'],authorization_id='explicit-answer')
            recovery.advance_project_recovery(row['taskId'],row['planSha256'],actor='patch')
            recovery.advance_project_recovery(row['taskId'],row['planSha256'],actor='jarvis')
            self.assertEqual(load(path)['retryAuthorization']['status'],'consumed')
            self.assertEqual(recovery.recovery_blocker(load(path),self.agenda),'authentication_required')
            result=recovery.advance_project_recovery(row['taskId'],row['planSha256'],actor='jarvis')
            self.assertEqual(result['status'],'held');classify.assert_called_once()
    def test_evidence_review_tools_cannot_dispatch_or_mutate_original_agenda(self):
        from agents import crew_reasoning as crew
        row={'origin':'evidence-review','permissions':{'execute':True,'repair':True}}
        for tool in ('dispatch','retry_conference','propose_patch','ask_ceo','save_knowhow','ingest_url','browser_observe'):
            with self.assertRaisesRegex(ValueError,'read-only'):
                crew.tool_call(row,tool,{})
        with patch.object(agendas,'propose') as propose,patch.object(agendas,'_save') as save:
            crew.ensure_business_agenda(row,'original')
            self.assertEqual(row['businessAgendaId'],'original');propose.assert_not_called();save.assert_not_called()

    def test_registered_original_agenda_evidence_reads_exact_bytes_with_hash(self):
        from agents import crew_reasoning as crew
        identity='b'*64;rows=self.root/'dashboard/data/publication-conferences/operations'
        path=rows/(identity+'.json')
        write(path,{'id':identity,'kind':'cro_widget_retrofit','auxiliaryResult':{'status':'held'}})
        before=path.read_bytes()
        with patch.object(crew,'ROOT',self.root),patch.object(agendas,'ROWS',rows):
            result=crew.tool_call({'origin':'evidence-review'},'evidence',{'name':'agenda:'+identity})
            self.assertEqual(result['sha256'],hashlib.sha256(before).hexdigest())
            self.assertEqual(result['data']['auxiliaryResult']['status'],'held')
            with self.assertRaises(ValueError):crew.read_evidence({'name':'agenda:../escape'})
        self.assertEqual(path.read_bytes(),before)

    def test_measurement_review_reads_registered_research_with_raw_hash_and_paging(self):
        from agents import crew_reasoning as crew
        key='measurement:review:cf-topic:2026-11-01/soulnote.kr'
        source=self.root/'cf_posting/output/scheduled/2026-11-01/soulnote.kr/research.json'
        state=self.root/'dashboard/data/active-agenda.json'
        write(source,{'claims':[{'claim':'one'},{'claim':'two'}],'status':'unknown'})
        write(state,{'unresolvedWork':{key:{'key':key,'sourceRef':str(source)}}})
        before=state.read_bytes();raw=source.read_bytes();name=crew.measurement_evidence_name(key)
        with patch.object(crew,'ROOT',self.root),patch.object(agendas,'STATE',state):
            result=crew.tool_call({'origin':'evidence-review'},'evidence',
                {'name':name,'select':['claims'],'limit':1})
            self.assertEqual(result['data'],[{'claim':'one'}])
            self.assertEqual(result['sha256'],hashlib.sha256(raw).hexdigest())
            self.assertEqual(result['followupKey'],key);self.assertEqual(result['evidenceName'],name)
            self.assertEqual(result['pagination']['nextOffset'],1)
            page=crew.read_evidence({'name':name,'select':['claims'],'offset':1,'limit':1})
            self.assertEqual(page['data'],[{'claim':'two'}]);self.assertEqual(page['sha256'],result['sha256'])
            write(source,{'claims':[{'claim':'changed'}]})
            self.assertNotEqual(crew.read_evidence({'name':name})['sha256'],result['sha256'])
        self.assertEqual(state.read_bytes(),before)

    def test_measurement_review_refuses_unregistered_keys_and_unapproved_paths(self):
        from agents import crew_reasoning as crew
        key='measurement:review:one';name=crew.measurement_evidence_name(key)
        state=self.root/'state.json'
        with patch.object(crew,'ROOT',self.root),patch.object(agendas,'STATE',state):
            write(state,{'unresolvedWork':{}})
            with self.assertRaisesRegex(ValueError,'Unknown measurement'):crew.read_evidence({'name':name})
            for source in ('../outside.json','dashboard/data/../data/revenue.json',
                           str(self.root.parent/'outside.json'),'dashboard/data/radar/scout.sqlite3',
                           'dashboard/data/credentials.json','cf_posting/output/scheduled/2026-11-01/soulnote.kr/secret.json'):
                with self.subTest(source=source):
                    write(state,{'unresolvedWork':{key:{'key':key,'sourceRef':source}}})
                    with self.assertRaises(ValueError):crew.read_evidence({'name':name})
            write(state,{'unresolvedWork':{key:{'key':'other','sourceRef':'dashboard/data/revenue.json'}}})
            with self.assertRaisesRegex(ValueError,'Unknown measurement'):crew.read_evidence({'name':name})

    def test_measurement_review_denies_symlink_ancestor_and_oversized_source(self):
        from agents import crew_reasoning as crew
        key='measurement:review:one';name=crew.measurement_evidence_name(key)
        source=self.root/'dashboard/data/revenue.json';state=self.root/'state.json'
        write(source,{'status':'unknown'});write(state,{'unresolvedWork':{key:{'key':key,'sourceRef':str(source)}}})
        original=Path.is_symlink
        with patch.object(crew,'ROOT',self.root),patch.object(agendas,'STATE',state):
            # Windows may not grant symlink creation; exercise ancestor rejection without requiring admin rights.
            with patch.object(Path,'is_symlink',lambda path:path==source.parent or original(path)):
                with self.assertRaisesRegex(ValueError,'Symlink'):crew.read_evidence({'name':name})
            source.write_bytes(b' '*2_000_001)
            with self.assertRaisesRegex(ValueError,'bounded read'):crew.read_evidence({'name':name})

    def test_measurement_preload_is_claimed_idempotent_and_never_advances_or_resets_budget(self):
        from agents import crew_reasoning as crew
        key='measurement:review:one';identity='c'*64
        source=self.root/'dashboard/data/revenue.json';state=self.root/'state.json';goals=self.root/'goals'
        write(source,{'status':'partial','value':None})
        write(state,{'unresolvedWork':{key:{'key':key,'sourceRef':str(source)}}})
        row={'id':identity,'businessAgendaId':'review-one','origin':'evidence-review','status':'ready',
             'permissions':{'execute':False,'repair':False},'decisions':1,'maxSteps':4,'observations':[]}
        write(goals/(identity+'.json'),row)
        agenda={'source':{'evidenceReview':True,'originalWorkRefs':{'followupKey':key}},
                'businessExperiment':{'id':'shared','maxModelCalls':20}}
        with patch.object(crew,'ROOT',self.root),patch.object(crew,'GOALS',goals), \
             patch.object(agendas,'STATE',state),patch.object(agendas,'get',return_value=agenda), \
             patch.object(crew,'advance') as advance:
            with ThreadPoolExecutor(max_workers=2) as pool:
                list(pool.map(lambda _:crew.preload_measurement_review(identity,key),range(2)))
            result=crew.preload_measurement_review(identity,key)
            saved=load(goals/(identity+'.json'))
            self.assertTrue(result['preloaded']);self.assertEqual(len(saved['observations']),1)
            self.assertEqual(saved['observations'][0]['result']['reviewAfterDecision'],1)
            self.assertEqual(saved['observations'][0]['result']['sha256'],hashlib.sha256(source.read_bytes()).hexdigest())
            self.assertEqual(saved['goal'].count('Host supplied exact measurement evidence e0:'),1)
            self.assertIn('e0 in your final evidence_ids',saved['goal'])
            self.assertIn('partial coverage',saved['goal'])
            self.assertEqual((saved['decisions'],saved['maxSteps'],saved['status']),(1,4,'ready'))
            self.assertNotIn('resolution',saved);advance.assert_not_called()
            self.assertEqual(agenda['businessExperiment'],{'id':'shared','maxModelCalls':20})

    def test_measurement_preload_refuses_exhausted_goal_and_wrong_binding(self):
        from agents import crew_reasoning as crew
        key='measurement:review:one';identity='d'*64;goals=self.root/'goals';path=goals/(identity+'.json')
        row={'id':identity,'businessAgendaId':'review-one','origin':'evidence-review','status':'answered',
             'permissions':{'execute':False,'repair':False},'decisions':4,'maxSteps':4,'observations':[]}
        write(path,row);before=path.read_bytes()
        agenda={'source':{'evidenceReview':True,'originalWorkRefs':{'followupKey':key}}}
        with patch.object(crew,'GOALS',goals),patch.object(agendas,'get',return_value=agenda), \
             patch.object(crew,'read_evidence') as read:
            result=crew.preload_measurement_review(identity,key)
            self.assertFalse(result['preloaded']);self.assertEqual(path.read_bytes(),before);read.assert_not_called()
            with self.assertRaisesRegex(ValueError,'bound review scope'):
                crew.preload_measurement_review(identity,'measurement:other')
            row.update(status='ready',decisions=0);row['permissions']['execute']=True;write(path,row)
            with self.assertRaisesRegex(ValueError,'bound review scope'):crew.preload_measurement_review(identity,key)

    def test_review_request_replay_preserves_host_instruction_and_spent_step_allowance(self):
        from agents import crew_reasoning as crew
        request='evidence-review:replay';identity=hashlib.sha256(request.encode()).hexdigest();goals=self.root/'goals'
        row={'id':identity,'goal':'Original question plus exact host evidence instruction','origin':'evidence-review',
             'status':'answered','decisions':4,'maxSteps':4,'observations':[]}
        write(goals/(identity+'.json'),row)
        with patch.object(crew,'GOALS',goals),patch.object(crew,'ensure_business_agenda'),patch.object(crew,'advance') as advance:
            result=crew.reason_request(request,'Original question',steps=0,max_steps=4,origin='evidence-review')
            self.assertEqual((result['status'],result['decisions'],result['maxSteps']),('answered',4,4))
            self.assertEqual(result['goal'],row['goal']);advance.assert_not_called()

    def test_volatile_clock_pid_and_context_changes_do_not_reopen(self):
        path,row=self.make_row(status='held',errorCode='classify:ValueError')
        changed=copy.deepcopy(row['discovered'])
        changed['environment']['browserWindow'].update(browserPid=99,windowId=234,observedAt=999)
        changed['environment']['resourceAvailability']={'quota':12}
        changed['fileHashes']['unrelated.py']='new-hash'
        self.assertFalse(recovery._recheck_recovery(path,row,changed))
        self.assertEqual(load(path)['status'],'held')

    def test_material_change_reopens_once_and_has_finite_lifetime_budget(self):
        path,row=self.make_row(status='evidence_hold')
        for index in range(3):
            row=load(path);row['status']='evidence_hold';write(path,row)
            changed=copy.deepcopy(row['discovered']);changed['fileHashes']['worker.py']=str(index)
            self.assertEqual(recovery._recheck_recovery(path,row,changed),index<2)
        self.assertEqual(load(path)['materialEvidenceReopens'],2)
        self.assertEqual(len(load(path)['evidenceHistory']),2)
        self.assertEqual(load(path)['status'],'evidence_hold')

    def test_deterministic_discovery_retry_is_bounded_and_classify_error_is_not_transient(self):
        path,row=self.make_row(step='discover',status='held',errorCode='discover:TimeoutError')
        for index in range(3):
            row=load(path);row.update(step='discover',status='held',errorCode='discover:TimeoutError');write(path,row)
            self.assertEqual(recovery._recheck_recovery(path,row,row['discovered']),index<2)
        self.assertEqual(load(path)['readonlyRetries'],2)
        row=load(path);row.update(errorCode='classify:ValueError',readonlyRetries=0);write(path,row)
        self.assertFalse(recovery._recheck_recovery(path,row,row['discovered']))

    def test_concurrent_dispatch_and_restart_enqueue_once(self):
        self.make_row()
        with patch.object(agendas,'enabled',return_value=False), \
             patch.object(agent_tools,'enqueue_staff_request',return_value={'requestId':'claimed'}) as queue:
            with ThreadPoolExecutor(max_workers=2) as pool:
                results=list(pool.map(lambda _:recovery.dispatch_project_recovery_once(),range(2)))
            self.assertEqual(sorted(results),[False,True])
            self.assertFalse(recovery.dispatch_project_recovery_once())
            queue.assert_called_once()

    def test_queued_staff_budget_hold_preserves_prior_receipts(self):
        self.budget()
        path=self.requests/'request.json'
        write(path,{'requestId':'request','taskId':'staff:original','status':'queued','businessAgendaId':'agenda-one',
                    'actions':[],'results':[{'prior':'history'}]})
        with patch.object(agendas,'enabled',return_value=True),patch.object(agendas,'active_ids',return_value=['agenda-one']), \
             patch.object(agendas,'get',return_value=self.agenda),patch('common.ego_executor.execute_staff_action') as execute:
            self.assertFalse(agent_tools.process_staff_request_once())
            self.assertFalse(agent_tools.process_staff_request_once())
            self.assertEqual(load(path)['status'],'held')
            self.assertEqual(load(path)['results'],[{'prior':'history'}]);execute.assert_not_called()

    def test_nonqueued_threads_submission_never_resumes(self):
        import sqlite3
        path,row=self.make_row()
        data=self.root/'dashboard/data';data.mkdir(parents=True)
        source=data/'original.json'
        args={'partId':'part','account':'one','date':'2026-11-03','slot':'19:10'}
        original={'kind':'threads','status':'failed','businessAgendaId':'agenda-one','arguments':args}
        write(source,original)
        row['plan'].update(originalRequestPath=str(source),originalRequestSha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                           sourcePath=str(source),projectRoot=str(self.root))
        with sqlite3.connect(data/'threads.sqlite3') as db:
            db.execute('create table parts(part_id text,state text,account_key text,publication_date text,slot text)')
            db.execute('insert into parts values(?,?,?,?,?)',('part','submitting','one','2026-11-03','19:10'))
        db.close()
        with patch.object(agendas,'require',return_value=self.agenda),patch.object(agendas,'running',return_value=False):
            with self.assertRaisesRegex(ValueError,'read-only reconciliation'):recovery._recovery_resume_guard(row)

    def test_ceo_exact_blocker_concurrent_dedup_and_original_task_links(self):
        path=self.root/'ceo.json'
        context={'project':'threads','account':'one','targetKey':'exact-url-and-part','securityScope':'publish',
                 'reasonCode':'login_required','resumeCondition':'verified_login'}
        def emit(index):
            return bridge.emit_ceo_proposal('jarvis','login '+str(index),'failed','refresh login',['login'],
                blocker_context=context,original_work={'agendaId':'agenda-one','goalId':'goal-'+str(index)})
        with patch.object(bridge,'CEO_PROPOSALS_FILE',path):
            with ThreadPoolExecutor(max_workers=3) as pool:results=list(pool.map(emit,range(3)))
            self.assertEqual(len({r['proposal']['id'] for r in results}),1)
            stored=load(path)['proposals'][0]
            self.assertEqual(stored['occurrences'],3);self.assertEqual(len(stored['originalWorkRefs']),3)
            self.assertFalse(stored['resumeAuthorized'])
            emit(4);self.assertEqual(len(load(path)['proposals']),1)

    def test_ceo_distinct_account_target_security_never_merge(self):
        path=self.root/'ceo.json'
        base={'project':'threads','account':'one','targetKey':'url-one','securityScope':'publish',
              'reasonCode':'login_required','resumeCondition':'verified_login'}
        with patch.object(bridge,'CEO_PROPOSALS_FILE',path):
            for change in ({},{'account':'two'},{'targetKey':'url-two'},{'securityScope':'delete'}):
                bridge.emit_ceo_proposal('jarvis','same','same','same',['same'],blocker_context={**base,**change})
        self.assertEqual(len(load(path)['proposals']),4)

    def test_existing_duplicate_consolidation_preserves_history_and_decisions(self):
        path=self.root/'ceo.json'
        context={'project':'threads','account':'one','reasonCode':'login_required','resumeCondition':'verified_login'}
        with patch.object(bridge,'CEO_PROPOSALS_FILE',path):
            first=bridge.emit_ceo_proposal('jarvis','same','same','same',['same'],blocker_context=context)['proposal']
            duplicate={**first,'id':'old-duplicate','currentReality':'old evidence'}
            write(path,{'proposals':[first,duplicate]})
            bridge.emit_ceo_proposal('jarvis','same','same','same',['same'],blocker_context=context)
            saved=load(path)['proposals']
            self.assertEqual(len(saved),2);self.assertEqual(saved[1]['status'],'consolidated')
            self.assertEqual(saved[1]['currentReality'],'old evidence')
            self.assertEqual(saved[1]['duplicateOf'],first['id'])
            saved[0]['status']='approved';saved[0]['decision']={'responseId':'ceo-answer','scope':'login'}
            write(path,{'proposals':saved})
            result=bridge.emit_ceo_proposal('jarvis','changed','same','expanded',['publish'],blocker_context=context)
            self.assertEqual(result['proposal']['decision'],{'responseId':'ceo-answer','scope':'login'})
            self.assertTrue(result['proposal']['followupReviewRequired'])
            self.assertFalse(result['proposal']['resumeAuthorized'])


if __name__=='__main__':unittest.main()
