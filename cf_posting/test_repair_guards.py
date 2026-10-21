import copy
import ast
import json
import datetime
import hashlib
import unittest
import tempfile
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import Mock, patch

SOURCE=Path(__file__).with_name('pipeline_runner.py').read_text(encoding='utf-8')
MODULE=ast.Module(body=[n for n in ast.parse(SOURCE).body if isinstance(n,ast.FunctionDef) and n.name in {'editorial_seed_failure','publication_may_be_inflight','_repair_preflight','_item_digest','report_cf_host_failure','resume_editorial_seed_repair','verify_repair_query_binding','approved_repair_query'}],type_ignores=[])
class RepairGuardTests(unittest.TestCase):
 def setUp(self):
  self.ns={'datetime':datetime,'hashlib':hashlib,'json':json,'KST':datetime.timezone(datetime.timedelta(hours=9)), 'publication_receipt':lambda item:Mock(exists=lambda:item.get('receipt',False))}
  exec(compile(MODULE,'production-repair-guards','exec'),self.ns)
  self.title='아이와 주말 수목원 나들이 예약 현장 발권 확인 동선'
  self.item={'status':'failed','currentStage':1,'growthKeyword':{'keyword':self.title+' — 취소 조건'},'lastError':'No eligible demand candidate: '+self.title+' unknown=HTTP 400'}
 def test_exact_known_failure_only(self):
  self.assertTrue(self.ns['editorial_seed_failure'](self.item))
  self.item['lastError']='No eligible demand candidate: 수목원 bounds=0..18'
  self.assertFalse(self.ns['editorial_seed_failure'](self.item))
 def test_submission_and_used_continuation_block(self):
  for field in ['receipt','submissionStarted','submissionStartedAt','submittedAt','repairContinuationUsed']:
   self.assertFalse(self.ns['editorial_seed_failure']({**self.item,field:True}),field)
 def test_changed_failure_stage_blocks(self):
  self.assertFalse(self.ns['editorial_seed_failure']({**self.item,'currentStage':2}))
 def test_pre_review_requires_fresh_public_inventory(self):
  today=datetime.datetime.now(self.ns['KST']).date().isoformat()
  self.item.update(domain='tripmarvel.com',slug='target',title='target title')
  self.ns.update(reconcile_item=Mock(return_value=False),requests=Mock(),SCHEDULE_JSON=Mock(read_bytes=lambda:b'schedule'))
  response=Mock();response.json.return_value={'posts':[]};self.ns['requests'].get.return_value=response
  proof={'date':today,'itemSha256':self.ns['_item_digest'](self.item)}
  observed=self.ns['_repair_preflight']({'date':today},self.item,proof)
  self.assertEqual(observed['exactMatches'],0)
  self.assertFalse(observed['submissionStarted'])
  self.ns['requests'].get.assert_called_once()
  response.json.return_value={'posts':[{'slug':'target','title':'target title'}]}
  with self.assertRaisesRegex(ValueError,'duplicate'):
   self.ns['_repair_preflight']({'date':today},self.item,proof)

 def test_host_failure_reports_actual_errors_but_not_quality_holds(self):
  with patch('common.host_failure.report_host_failure') as report:
   self.ns['report_cf_host_failure']({**self.item,'lastError':'MaterialRequired: missing source'}, {'date':'2026-10-21'},Path('schedule.json'))
   report.assert_not_called()
   self.ns['report_cf_host_failure']({**self.item,'domain':'tripmarvel.com','lastError':'FileNotFoundError: missing image'}, {'date':'2026-10-21'},Path('schedule.json'))
   report.assert_called_once()
   self.assertEqual(report.call_args.kwargs['error_type'],'FileNotFoundError')


class ResumeBoundaryTests(unittest.TestCase):
 def setUp(self):
  RepairGuardTests.setUp(self)
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.root=Path(self.tmp.name);self.schedule=self.root/'schedule.json'
  self.task='cf-repair:fixture:tripmarvel.com';self.kind='editorial_seed_pinned_as_keyword'
  self.fp=hashlib.sha256((self.task+'|'+self.kind).encode()).hexdigest()
  self.item.update(domain='tripmarvel.com',slug='target',title='target title',attemptCount=3)
  self.doc={'date':datetime.datetime.now(self.ns['KST']).date().isoformat(),'items':[self.item]}
  self.save(self.schedule,self.doc)
  self.proof={'domain':self.item['domain'],'date':self.doc['date'],'failureType':self.kind,'itemSha256':self.ns['_item_digest'](self.item),'repairDirectory':str(self.root)}
  self.permit={'taskId':self.task,'repairRevision':hashlib.sha256(Path(__file__).with_name('pipeline_runner.py').read_bytes()).hexdigest(),'resumeLimit':1,'failureEvidenceSha256':'failure','repairEvidenceSha256':'repair','verdict':dict.fromkeys(['supported','gatesPreserved','sameTask','safeToResume'],True)}
  self.permit_path=self.root/(self.fp+'.permit.json');self.save(self.permit_path,self.permit)
  self.save(self.root/(self.fp+'.json'),{'status':'resuming','resumeAttempted':True,'failureEvidenceSha256':'failure'})
  self.save(self.root/(self.fp+'.resume.json'),{'taskId':self.task,'controllerFingerprint':self.fp})
  self.repaired={'resumePermitPath':str(self.permit_path),'resumePermitSha256':hashlib.sha256(self.permit_path.read_bytes()).hexdigest(),'evidenceSha256':'repair'}
  response=Mock();response.json.return_value={'posts':[]}
  self.publisher=Mock(side_effect=self.publish_fixture)
  self.ns.update(Path=Path,__file__=str(Path(__file__).with_name('pipeline_runner.py')),SCHEDULE_JSON=self.schedule,BASE_DIR=self.root,cleaner_lock=lambda:nullcontext(True),save_schedule_file=self.save,run_publisher_for_item=self.publisher,_REPAIR_AUTHORIZATION=object(),reconcile_item=Mock(return_value=False),requests=Mock(),ReviewRequired=RuntimeError)
  self.ns['requests'].get.return_value=response
  self.addCleanup(patch.stopall);patch('common.repair_workflow.ROOT',self.root).start()
 def save(self,path,value):Path(path).write_text(json.dumps(value),encoding='utf-8')
 def publish_fixture(self,item,schedule,path,**kwargs):
  self.assertIs(kwargs['_repair_authorization'],self.ns['_REPAIR_AUTHORIZATION'])
  self.assertEqual(item['attemptCount'],3)
  item['attemptCount']+=1;item['status']='failed';item['lastExitCode']=1
  self.save(path,schedule);return False
 def invoke(self):return self.ns['resume_editorial_seed_repair'](self.task,self.proof,self.repaired)
 def test_valid_permit_runs_boundary_once_preserving_attempt_history(self):
  result=self.invoke();self.assertEqual(result['attemptCount'],4);self.publisher.assert_called_once()
  with self.assertRaises(ValueError):self.invoke()
  self.publisher.assert_called_once()
 def test_changed_permit_never_calls_publisher(self):
  self.permit_path.write_text('{}',encoding='utf-8')
  with self.assertRaisesRegex(ValueError,'permit changed'):self.invoke()
  self.publisher.assert_not_called()
 def test_unknown_used_and_duplicate_never_call_publisher(self):
  for field in ['submittedAt','repairContinuationUsed']:
   changed=json.loads(json.dumps(self.doc));changed['items'][0][field]=True;self.save(self.schedule,changed)
   with self.assertRaises(ValueError):self.invoke()
  self.save(self.schedule,self.doc)
  self.ns['requests'].get.return_value.json.return_value={'posts':[{'slug':'target','title':'target title'}]}
  with self.assertRaisesRegex(ValueError,'duplicate'):self.invoke()
  self.publisher.assert_not_called()
 def test_busy_lock_never_calls_publisher(self):
  self.ns['cleaner_lock']=lambda:nullcontext(False)
  with self.assertRaisesRegex(RuntimeError,'active'):self.invoke()
  self.publisher.assert_not_called()
 def test_mismatched_shared_budget_never_calls_publisher(self):
  self.save(self.root/(self.fp+'.resume.json'),{'taskId':'different','controllerFingerprint':self.fp})
  with self.assertRaisesRegex(ValueError,'budget'):self.invoke()
  self.publisher.assert_not_called()
 def test_changed_original_review_never_calls_publisher(self):
  v2=hashlib.sha256((self.fp+'|review-v2').encode()).hexdigest()
  path=self.root/(v2+'.permit.json');self.save(path,self.permit)
  self.repaired.update(resumePermitPath=str(path),resumePermitSha256=hashlib.sha256(path.read_bytes()).hexdigest())
  self.save(self.root/(v2+'.json'),{'status':'resuming','resumeAttempted':True,'previousFingerprint':self.fp,'oldReviewSha256':'changed'})
  self.save(self.root/(self.fp+'.resume.json'),{'taskId':self.task,'controllerFingerprint':v2})
  with self.assertRaisesRegex(ValueError,'Original rejected'):self.invoke()
  self.publisher.assert_not_called()


 def test_v3_reviewed_query_reaches_child_input_without_changing_history(self):
  query={'candidates':[{'mainKeyword':'arboretum booking'}],'measurements':{'candidates':[{'eligible':True}]}}
  qp=self.root/'query.json';self.save(qp,query);qsha=hashlib.sha256(qp.read_bytes()).hexdigest()
  ip=self.root/'intent.json';self.save(ip,{'queryEvidenceSha256':qsha,'verdict':{'judgments':[{'index':0,'sameIntent':True}]}})
  binding={'approvedQuery':'arboretum booking','queryEvidenceSha256':qsha,'intentEvidenceSha256':hashlib.sha256(ip.read_bytes()).hexdigest()}
  ev=self.root/'validation.json';self.save(ev,{**binding,'queryEvidencePath':str(qp),'intentEvidencePath':str(ip)})
  self.repaired.update(evidencePath=str(ev),evidenceSha256=hashlib.sha256(ev.read_bytes()).hexdigest())
  revision=getattr(self,'review_revision',3)
  previous=hashlib.sha256((self.fp+'|review-v'+str(revision-1)).encode()).hexdigest()
  old=self.root/(previous+'.json');self.save(old,{'status':'review_rejected','resumeAttempted':False})
  v3=hashlib.sha256((self.fp+'|review-v'+str(revision)).encode()).hexdigest()
  self.permit.update(reviewedInputs=binding,repairEvidenceSha256=self.repaired['evidenceSha256'])
  path=self.root/(v3+'.permit.json');self.save(path,self.permit)
  self.repaired.update(resumePermitPath=str(path),resumePermitSha256=hashlib.sha256(path.read_bytes()).hexdigest())
  self.save(self.root/(v3+'.json'),{'status':'resuming','resumeAttempted':True,'failureEvidenceSha256':'failure','previousFingerprint':previous,'oldReviewSha256':hashlib.sha256(old.read_bytes()).hexdigest()})
  self.save(self.root/(self.fp+'.resume.json'),{'taskId':self.task,'controllerFingerprint':v3})
  original_growth=self.item['growthKeyword'].copy()
  self.invoke()
  scheduled=json.loads(self.schedule.read_text())['items'][0]
  self.assertEqual(scheduled['growthKeyword'],original_growth)
  self.assertNotIn('mainKeyword',scheduled)
  self.assertEqual(self.ns['approved_repair_query'](scheduled),'arboretum booking')
  qp.write_text('{}',encoding='utf-8')
  with self.assertRaisesRegex(ValueError,'Query proof changed'):self.ns['approved_repair_query'](scheduled)

 def test_v4_requires_previous_review_and_bound_query(self):
  self.review_revision=4
  self.test_v3_reviewed_query_reaches_child_input_without_changing_history()

class CleanerOwnershipTests(unittest.TestCase):
 def test_nested_owner_and_competing_thread_process(self):
  import os,time,threading,asyncio,subprocess,sys
  from contextlib import contextmanager
  node=next(n for n in ast.parse(SOURCE).body if isinstance(n,ast.FunctionDef) and n.name=='cleaner_lock')
  ns=dict(Path=Path,os=os,time=time,contextmanager=contextmanager,_cleaner_threading=threading,_cleaner_asyncio=asyncio,_CLEANER_OWNERS=threading.local())
  exec(compile(ast.Module(body=[node],type_ignores=[]),'actual-cleaner-lock','exec'),ns)
  with tempfile.TemporaryDirectory() as temp:
   path=Path(temp)/'lock'
   with ns['cleaner_lock'](path) as acquired:
    self.assertTrue(acquired)
    with ns['cleaner_lock'](path) as nested:self.assertTrue(nested)
    observations=[]
    def compete():
     with ns['cleaner_lock'](path) as other:observations.append(other)
    t=threading.Thread(target=compete);t.start();t.join();self.assertEqual(observations,[False])
    child="import os,sys; f=open(sys.argv[1],'a+b'); f.seek(0); " + ("import msvcrt; msvcrt.locking(f.fileno(),msvcrt.LK_NBLCK,1)" if os.name=='nt' else "import fcntl; fcntl.flock(f.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)")
    result=subprocess.run([sys.executable,'-c',child,str(path)],capture_output=True)
    self.assertNotEqual(result.returncode,0)
   with ns['cleaner_lock'](path) as after:self.assertTrue(after)


class IndependentReviewTests(unittest.TestCase):
 def run_review(self,result):
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp)
   for name in ('assembled.html','article.json','final.html'):(root/name).write_text('fixture',encoding='utf-8')
   handoff=Mock(folder=root,data={'runId':'fixture'});handoff.file.side_effect=lambda name:root/name
   layout={'finalSha256':'digest','screenshots':[]}
   def document(path):
    if path.name=='images.md':return {'imagePlans':[]}
    if path.name=='layout-evidence.md':return layout
    return {}
   ns={'BLOG_REQUIRED_CHECKS':('readerTask',),'RUN_CONTEXT':{},'read_document':document,'validate_reader_task':Mock(),'validate_images':Mock(),'digest':lambda path:'digest','review_visual_assets':Mock(return_value={'batches':[]}),'review_layout_groups':Mock(return_value=[]),'agent_prompt':lambda *args:'fixture','BLOG_REVIEW_POLICY':'','ReviewRequired':RuntimeError,'stamp':lambda:'fixture','content_quality_sha256':lambda:'policy','json':json,'validate_visual_review_coverage':Mock(),'visual_review_outputs':lambda *args:[]}
   node=next(n for n in ast.parse(SOURCE).body if isinstance(n,ast.FunctionDef) and n.name=='review_article')
   exec(compile(ast.Module(body=[node],type_ignores=[]),'actual-review-article','exec'),ns)
   with patch('common.content_improvement.audit_article',return_value={}):
    try:ns['review_article'](handoff,{},Mock(return_value=result),lambda:'fixture-model')
    except RuntimeError:rejected=True
    else:rejected=False
   saved=json.loads((root/'review.json').read_text(encoding='utf-8'))
   return rejected,saved,handoff.accept.call_count
 def test_actual_rejection_preserved_and_never_accepted(self):
  original={'status':'rejected','issues':['unsupported fact'],'checks':{'readerTask':True,'factsSupported':False},'notes':[]}
  rejected,saved,accepted=self.run_review(original)
  self.assertTrue(rejected);self.assertEqual(accepted,0)
  for field in ('status','issues','checks'):self.assertEqual(saved[field],original[field])
 def test_missing_and_false_required_checks_block(self):
  for checks in ({'readerTask':True},{'readerTask':True,'factsSupported':False}):
   rejected,_,accepted=self.run_review({'status':'passed','issues':[],'checks':checks,'notes':[]})
   self.assertTrue(rejected);self.assertEqual(accepted,0)
 def test_actual_pass_is_accepted_without_rewriting_verdict(self):
  result={'status':'passed','issues':[],'checks':{'readerTask':True,'factsSupported':True},'notes':['observed']}
  rejected,saved,accepted=self.run_review(result)
  self.assertFalse(rejected);self.assertEqual(accepted,1);self.assertEqual(saved['notes'],['observed'])


class VisualAndAssemblyVerdictTests(unittest.TestCase):
 def test_visual_result_is_preserved_then_actual_validator_rejects(self):
  import copy,uuid
  names={'call_visual_batch','_review_visual_group'}
  nodes=[n for n in ast.parse(SOURCE).body if isinstance(n,ast.FunctionDef) and n.name in names]
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp);image=root/'image.png';image.write_bytes(b'controlled image fixture')
   plan={'filename':'image.png','stepId':'step'}
   attachments=[{'imageIndex':1,'filename':'image.png','stepId':'step','sha256':'digest'}]
   good={'checks':dict.fromkeys(['visualsServeTask','actualCaptureAlignment','captionsAccurate','generatedUseHonest'],True),'issues':[],'notes':[],'perImage':[{'imageIndex':1,'filename':'image.png','stepId':'step','observedContent':'actual fixture observation','alignment':True,'usable':True,'reason':'fixture'}]}
   cases=[]
   for field,value in [('usable',False),('alignment',False),('filename','wrong.png'),('observedContent','')]:
    row=copy.deepcopy(good);row['perImage'][0][field]=value;cases.append(row)
   row=copy.deepcopy(good);row['perImage']=[];cases.append(row)
   row=copy.deepcopy(good);row['checks']['captionsAccurate']=False;cases.append(row)
   ns={'Path':Path,'uuid':uuid,'copy':copy,'json':json,'ReviewRequired':RuntimeError,'digest':lambda p:'digest','validate_images':Mock(),'agent_prompt':lambda *a:'fixture','BLOG_REVIEW_POLICY':''}
   exec(compile(ast.Module(body=nodes,type_ignores=[]),'actual-visual-review','exec'),ns)
   handoff=Mock(folder=root)
   for result in cases:
    def generate(prompt,images=None,response_schema=None):
     record=ns['call_visual_batch'](handoff,'reviewer','source',attachments,prompt,images,Mock(return_value=result),lambda:'fixture-model',response_schema)
     self.assertEqual(record['response'],result)
     saved=json.loads((root/record['reportFile']).read_text(encoding='utf-8'));self.assertEqual(saved['response'],result)
     return record['response']
    with self.assertRaises(RuntimeError):ns['_review_visual_group']({'imagePlans':[plan]},[plan],[image],generate,attachments=attachments)
 def test_assembler_rejection_saved_without_stage_acceptance(self):
  node=next(n for n in ast.parse(SOURCE).body if isinstance(n,ast.FunctionDef) and n.name=='assemble_with_agent')
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp)
   for name in ('draft.md','assembled.html'):(root/name).write_text('fixture',encoding='utf-8')
   handoff=Mock(folder=root,data={});handoff.file.side_effect=lambda name:root/name
   record=Mock();result={'inputComplete':False,'assemblyReadyForLayoutReview':False,'issues':['missing required asset'],'notes':[],'edits':[]}
   ns={'preview':Mock(),'read_document':lambda p:{},'RUN_CONTEXT':{},'agent_prompt':lambda *a:'fixture','BLOG_REVIEW_POLICY':'','cosmetic_issues_only':lambda issues:False,'ReviewRequired':RuntimeError,'document':record,'json':json}
   exec(compile(ast.Module(body=[node],type_ignores=[]),'actual-assembler','exec'),ns)
   with self.assertRaises(RuntimeError):ns['assemble_with_agent'](handoff,{},[],[],Mock(return_value=result),lambda:'fixture')
   self.assertEqual(record.call_args.args[2],result);handoff.accept.assert_not_called()


class HandoffPolicyIntegrityTests(unittest.TestCase):
 def test_changed_policy_or_instruction_never_rewrites_approval(self):
  import copy
  cls=next(n for n in ast.parse(SOURCE).body if isinstance(n,ast.ClassDef) and n.name=='Handoff')
  check=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='check')
  ns={'content_quality_sha256':lambda:'current-policy','ReviewRequired':RuntimeError,'digest':lambda path:'current-instruction' if path.suffix=='.md' else 'artifact','BASE_DIR':Path('/fixture')}
  exec(compile(ast.Module(body=[check],type_ignores=[]),'actual-handoff-check','exec'),ns)
  base={'version':2,'contentQualitySha256':'current-policy','stages':[{'agent':'keyword-selector','contentQualitySha256':'current-policy','status':'accepted','inputs':[],'inputHashes':{},'fileHashes':{'result.json':'artifact'},'outputs':['result.json'],'instructionSha256':'current-instruction','model':{'status':'returned'}}]}
  for mutation in ('top','stage','instruction'):
   data=copy.deepcopy(base)
   if mutation=='top':data['contentQualitySha256']='old'
   elif mutation=='stage':data['stages'][0]['contentQualitySha256']='old'
   else:data['stages'][0]['instructionSha256']='old'
   before=copy.deepcopy(data);obj=Mock(data=data,agents=['keyword-selector']);obj.file.side_effect=Path
   with self.assertRaises(RuntimeError):ns['check'](obj)
   self.assertEqual(data,before);obj.save.assert_not_called()
  for optional in (True,False):
   data=copy.deepcopy(base)
   if optional:data['stages'][0].pop('instructionSha256')
   obj=Mock(data=data,agents=['keyword-selector']);obj.file.side_effect=Path
   self.assertEqual(len(ns['check'](obj)),1);obj.save.assert_not_called()

class AnswerBriefVerdictTests(unittest.TestCase):
 def setUp(self):
  from common import answer_brief as ab
  self.ab=ab
  self.goal={'question':'Question','successCondition':'Answer','requiredAnswers':['First']}
  self.brief={'sections':[{'id':'s1'}]}
  self.raw={'passed':True,'checks':dict.fromkeys(ab.BRIEF_CHECKS,True),'coverage':{'goal_0':{'answered':True,'sectionIds':['s1'],'reason':'Observed answer'}},'issues':[],'missingInputs':[]}
 def test_actual_pass_and_raw_identity_preserved(self):
  before=copy.deepcopy(self.raw)
  bound=self.ab.bind_brief_review_draft(self.raw,self.goal,self.brief)
  self.assertEqual(self.raw,before)
  self.assertEqual(bound['coverage'][0]['goalIndex'],0)
  self.assertTrue(self.ab.validate_brief_review(bound,self.brief,self.goal))
 def test_rejection_false_checks_coverage_and_issues_never_promoted(self):
  for kind in ('passed','checks','coverage','issues','missingInputs'):
   raw=copy.deepcopy(self.raw)
   if kind=='passed':raw['passed']=False
   elif kind=='checks':raw['checks'][self.ab.BRIEF_CHECKS[0]]=False
   elif kind=='coverage':raw['coverage']['goal_0']['answered']=False
   elif kind=='issues':raw['issues']=['Actual gap']
   else:raw[kind]=[{'kind':'source_fact','description':'Missing source','reason':'Cannot answer','acquisitionAction':'Read source'}]
   before=copy.deepcopy(raw)
   bound=self.ab.bind_brief_review_draft(raw,self.goal,self.brief)
   with self.assertRaises(self.ab.AnswerBriefBlocked):self.ab.validate_brief_review(bound,self.brief,self.goal)
   self.assertEqual(raw,before)
 def test_missing_or_wrong_identity_is_not_filled(self):
  for kind in ('absent','list','goal','section','observation','check'):
   raw=copy.deepcopy(self.raw)
   if kind=='absent':raw.pop('coverage')
   elif kind=='list':raw['coverage']=[]
   elif kind=='goal':raw['coverage']={'goal_7':raw['coverage']['goal_0']}
   elif kind=='section':raw['coverage']['goal_0']['sectionIds']=['invented']
   elif kind=='observation':raw['coverage']['goal_0']['reason']=''
   else:raw['checks'].pop(self.ab.BRIEF_CHECKS[0])
   before=copy.deepcopy(raw)
   with self.assertRaises(RuntimeError):self.ab.bind_brief_review_draft(raw,self.goal,self.brief)
   self.assertEqual(raw,before)
 def test_planner_gaps_and_context_selection_are_preserved(self):
  contexts=self.ab.prepare_question_context([{'id':'ctx','kind':'explicit_request','text':'Question'}])
  raw={'questionBasis':{'contextId':contexts[0]['id']},'readyForWriter':False,'missingInputs':[{'kind':'source_fact','description':'Source','reason':'Missing','acquisitionAction':'Read'}],'unresolvedQuestions':['Unanswered']}
  before=copy.deepcopy(raw)
  bound=self.ab.bind_answer_brief_draft(raw,self.goal,contexts)
  self.assertEqual(raw,before)
  for key in ('readyForWriter','missingInputs','unresolvedQuestions'):self.assertEqual(bound[key],raw[key])
  for bad in ({'questionBasis':{'contextId':'wrong'}},{'questionContextIds':['wrong']}):
   draft={**raw,**bad}
   if 'questionContextIds' in bad:draft.pop('questionBasis')
   with self.assertRaises(RuntimeError):self.ab.bind_answer_brief_draft(draft,self.goal,contexts)

if __name__=='__main__':unittest.main()
