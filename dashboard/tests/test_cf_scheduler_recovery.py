"""Isolated source-function regressions: no project imports, processes or network."""
import ast
from contextlib import nullcontext
import datetime
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from urllib.parse import urlparse
import uuid

ROOT = Path(__file__).resolve().parents[2]


def functions(relative, names, namespace):
    tree = ast.parse((ROOT / relative).read_text(encoding='utf-8'))
    selected = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    assert len(selected) == len(names)
    exec(compile(ast.Module(body=selected, type_ignores=[]), relative, 'exec'), namespace)
    return namespace


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def write(path, value, **kwargs):
    path.write_text(json.dumps(value), encoding='utf-8')


class CFRecovery(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='cf-recovery-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.folder = self.root / 'output' / 'draft'
        self.folder.mkdir(parents=True)
        self.schedule = self.root / 'schedule.json'
        self.day = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9))).date().isoformat()
        write(self.schedule, {'date': self.day, 'items': [{'domain': 'example.com', 'status': 'waiting'}]})
        jobs = ModuleType('common.dashboard_jobs')
        jobs.write = write
        self.addCleanup(patch.stopall)
        patch.dict(sys.modules, {'common': ModuleType('common'), 'common.dashboard_jobs': jobs}).start()
        patch.object(Path, 'home', return_value=self.root).start()
        self.ns = functions('cf_posting/posting.py', ['run_basic_posting', '_complete_basic_posting', 'record_basic_failure', 'slot_due'], {
            'Path': Path, 'datetime': datetime, 'json': json, 'uuid': uuid, 're': re,
            'BASE_DIR': self.root, 'SCHEDULE_JSON': self.schedule,
            'KST': datetime.timezone(datetime.timedelta(hours=9)), 'stamp': lambda: 'attempt-one',
            'load_current_schedule': lambda: read(self.schedule), 'save_schedule_file': write,
            'basic_progress': self.progress, 'basic_article': Mock(side_effect=ValueError('source evidence absent')),
            'publish_basic_article': Mock(),
        })

    def progress(self, domain, stage, name, pct, detail, status='processing'):
        doc = read(self.schedule)
        doc['items'][0].update(status=status, currentStage=stage)
        write(self.schedule, doc)

    def row(self):
        return read(self.schedule)['items'][0]

    def test_direct_conference_failure_updates_ledger_and_propagates_original(self):
        error = ValueError('source evidence absent')
        self.ns['basic_article'].side_effect = error
        with self.assertRaises(ValueError) as caught:
            self.ns['run_basic_posting']('example.com', self.folder)
        self.assertIs(caught.exception, error)
        self.assertEqual(self.row()['status'], 'failed')
        self.assertEqual(self.row()['attemptCount'], 1)
        self.assertIn('source evidence absent', self.row()['lastError'])
        self.assertIn('nextRetryAt', self.row())
        self.ns['publish_basic_article'].assert_not_called()

    def test_receipt_presence_fences_failure_even_if_unreadable(self):
        for receipt in ('{"state":"accepted"}', '{"state":"submission_unknown"}', 'broken json'):
            with self.subTest(receipt=receipt):
                write(self.schedule, {'date':self.day, 'items':[{'domain':'example.com','status':'waiting'}]})
                (self.folder / 'publication-receipt.json').unlink(missing_ok=True)
                def fail_after_receipt(*args):
                    (self.folder / 'publication-receipt.json').write_text(receipt)
                    raise ValueError('submission result unknown')
                self.ns['basic_article'].side_effect = None
                self.ns['basic_article'].return_value = {'title':'Title','topicSlug':'article'}
                self.ns['publish_basic_article'].side_effect = fail_after_receipt
                with self.assertRaises(ValueError):
                    self.ns['run_basic_posting']('example.com', self.folder)
                self.assertEqual(self.row()['status'], 'verification_pending')
                self.assertFalse(self.row()['retryable'])
                self.assertNotIn('nextRetryAt', self.row())
                self.assertEqual((self.folder / 'publication-receipt.json').read_text(), receipt)
                self.assertFalse(self.ns['slot_due'](self.row(), datetime.datetime.now(self.ns['KST'])))

    def test_existing_receipt_holds_before_progress_and_attempt_mutation(self):
        before = read(self.schedule)
        (self.folder / 'publication-receipt.json').write_text('{"state":"accepted"}')
        with self.assertRaisesRegex(RuntimeError, 'receipt requires reconciliation'):
            self.ns['run_basic_posting']('example.com', self.folder)
        self.assertEqual(read(self.schedule), before)
        self.ns['basic_article'].assert_not_called()
        self.ns['publish_basic_article'].assert_not_called()

    def test_missing_article_cannot_abandon_original_receipt_folder(self):
        doc = read(self.schedule)
        doc['items'][0]['artifactFolder'] = str(self.folder.relative_to(self.root))
        write(self.schedule, doc)
        (self.folder / 'publication-receipt.json').write_text('{"state":"submission_unknown"}')
        with self.assertRaisesRegex(RuntimeError, 'requires reconciliation'):
            self.ns['run_basic_posting']('example.com')
        self.assertEqual(read(self.schedule), doc)
        self.assertEqual(list((self.root/'output').iterdir()), [self.folder])

    def test_explicit_alternate_folder_cannot_bypass_authoritative_receipt(self):
        for state in ('accepted','submission_unknown'):
            with self.subTest(state=state):
                doc=read(self.schedule);doc['items'][0]['artifactFolder']=str(self.folder.relative_to(self.root))
                write(self.schedule,doc);write(self.folder/'publication-receipt.json',{'state':state})
                alternate=self.root/'output/alternate'
                with self.assertRaisesRegex(RuntimeError,'Authoritative artifact folder'):
                    self.ns['run_basic_posting']('example.com',alternate)
                self.assertEqual(read(self.schedule),doc);self.assertFalse(alternate.exists())

    def test_published_return_is_unchanged_without_authoring_or_submission(self):
        doc = read(self.schedule)
        doc['items'][0].update(status='published', publicUrl='https://example.com/article')
        write(self.schedule, doc)
        result = self.ns['run_basic_posting']('example.com', self.folder)
        self.assertEqual(result['state'], 'published')
        self.assertEqual(read(self.schedule), doc)
        self.ns['basic_article'].assert_not_called()
        self.ns['publish_basic_article'].assert_not_called()

    def test_successful_attempt_persists_verified_publication(self):
        self.ns['basic_article'].side_effect = None
        self.ns['basic_article'].return_value = {'title':'Title', 'topicSlug':'article'}
        receipt = {'state':'published','publicUrl':'https://example.com/article','verifiedAt':'2026-11-03T00:00:00Z'}
        self.ns['publish_basic_article'].return_value = receipt
        with patch.dict(sys.modules, {'dashboard.collectors.metrics':None}), patch('builtins.print'):
            result = self.ns['run_basic_posting']('example.com', self.folder)
        self.assertEqual(result, receipt)
        self.assertEqual(self.row()['status'], 'published')
        self.assertEqual(self.row()['publicUrl'], receipt['publicUrl'])
        self.assertNotIn('nextRetryAt', self.row())

    def test_recording_preserves_unknown_and_submitted_states(self):
        for status in ('unknown', 'submitting', 'submission_unknown', 'accepted', 'submitted', 'pending_effect'):
            with self.subTest(status=status):
                doc = read(self.schedule)
                doc['items'][0].update(status=status, attemptStartedAt='attempt-one')
                write(self.schedule, doc)
                self.ns['record_basic_failure']('example.com', self.day, 'attempt-one', self.folder, ValueError('failed'))
                self.assertEqual(self.row()['status'], status)
                self.assertFalse(self.ns['slot_due'](self.row(), datetime.datetime.now(self.ns['KST'])))

    def test_direct_entry_cannot_erase_an_uncertain_or_held_state(self):
        for extra in ([{'status':status} for status in ('unknown','submitting','submission_unknown','accepted','submitted','verification_pending','published_verified','verified','pending_effect')]
                      + [{'status':'failed','retryable':False}, {'status':'failed','submissionStarted':True}, {'status':'failed','preCommitIntent':True}]):
            with self.subTest(extra=extra):
                doc = {'date':self.day,'items':[{'domain':'example.com',**extra}]}
                write(self.schedule, doc)
                with self.assertRaisesRegex(RuntimeError, 'requires reconciliation'):
                    self.ns['run_basic_posting']('example.com', self.folder)
                self.assertEqual(read(self.schedule), doc)
        self.ns['basic_article'].assert_not_called()
        self.ns['publish_basic_article'].assert_not_called()

    def test_recording_never_overwrites_new_day_attempt_success_or_ambiguous_domain(self):
        for change in ('date', 'attempt', 'published', 'duplicate'):
            with self.subTest(change=change):
                doc = {'date': self.day, 'items': [{'domain':'example.com', 'status':'processing', 'attemptStartedAt':'attempt-one'}]}
                if change == 'date': doc['date'] = '1999-01-01'
                if change == 'attempt': doc['items'][0]['attemptStartedAt'] = 'new-attempt'
                if change == 'published': doc['items'][0]['status'] = 'published'
                if change == 'duplicate': doc['items'].append(dict(doc['items'][0]))
                write(self.schedule, doc)
                self.ns['record_basic_failure']('example.com', self.day, 'attempt-one', self.folder, ValueError('failed'))
                self.assertEqual(read(self.schedule), doc)

    def test_failed_ledger_write_does_not_mask_original_failure(self):
        error = ValueError('original failure')
        self.ns['basic_article'].side_effect = error
        self.ns['record_basic_failure'] = Mock(side_effect=OSError('disk unavailable'))
        with self.assertRaises(ValueError) as caught:
            self.ns['run_basic_posting']('example.com', self.folder)
        self.assertIs(caught.exception, error)
        self.assertIn('OSError', caught.exception.__notes__[0])


class ConferenceBackoff(unittest.TestCase):
    def test_only_due_valid_retry_values_spawn(self):
        with tempfile.TemporaryDirectory(prefix='cf-dispatch-test-') as temp:
            root = Path(temp)
            queue = root / 'queue'
            queue.mkdir()
            agendas = ModuleType('common.work_agenda')
            agendas.enabled = lambda: False
            locks = ModuleType('common.runtime_locks')
            locks.process_start_ticks = lambda pid: 'started'
            process = Mock(return_value=SimpleNamespace(pid=123))
            ns = functions('dashboard/common/conference_dispatch.py', ['process_once', '_lane_for_row'], {
                'Path':Path, 'QUEUE':queue, 'ROOT':root, 'locked':lambda path:nullcontext(),
                'load':read, 'write':write, 'math':math, 'time':SimpleNamespace(time=lambda:1000),
                'os':SimpleNamespace(name='nt',environ={},pathsep=';'), 'sys':sys,
                'subprocess':SimpleNamespace(Popen=process), 'LANE_LIMITS':{'cf_blog':3},
            })
            with patch.dict(sys.modules, {'common':ModuleType('common'), 'common.work_agenda':agendas, 'common.runtime_locks':locks}), patch.object(Path, 'home', return_value=root):
                for value, expected in [(1001,False),(1000,True),(999,True),(0,True),(None,False),('999',False),(-1,False),(True,False),(float('nan'),False),(float('inf'),False)]:
                    with self.subTest(retryAt=value):
                        process.reset_mock()
                        write(queue/'request.json', {'status':'queued','kind':'parameters','arguments':{'action':'cf','account':'example.com'},'retryAt':value})
                        self.assertEqual(ns['process_once'](), expected)
                        self.assertEqual(process.call_count, int(expected))


class CFExactRecovery(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='cf-identity-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.queue = self.root/'queue'; self.queue.mkdir()
        self.folder = self.root/'cf_posting/output/draft'; self.folder.mkdir(parents=True)
        self.day = datetime.datetime.now(datetime.timezone.utc).astimezone(datetime.timezone(datetime.timedelta(hours=9))).date().isoformat()
        self.args = {'action':'cf-prepare','date':self.day,'account':'example.com','slot':'09:30'}
        self.current = {'id':'owner','project':'cf_blog','status':'recovering','workTarget':{'kind':'parameters','arguments':self.args}}
        self.identity = hashlib.sha256(json.dumps(['parameters',self.args],sort_keys=True).encode()).hexdigest()
        self.file = self.queue/(self.identity+'.json')
        self.original = {'kind':'parameters','arguments':self.args,'businessAgendaId':'owner','status':'failed',
                         'preparationOnly':True,'submissionStarted':False,'attempts':1,'requestedAt':1}
        write(self.file,self.original)
        self.schedule = self.root/'dashboard/data/cf/daily_schedule.json'; self.schedule.parent.mkdir(parents=True)
        write(self.schedule, {'date':self.day,'items':[{'domain':'example.com','status':'waiting'}]})
        write(self.folder/'article.json', {'title':'Corrected title'})
        agendas = ModuleType('common.work_agenda')
        agendas.running = Mock(return_value=[]); agendas.require = Mock(return_value=self.current); agendas.progress = Mock()
        parameters = ModuleType('common.channel_parameters')
        parameters.policy = lambda:{'cf':{'example.com':'09:30'}}
        parameters.KST = datetime.timezone(datetime.timedelta(hours=9)); parameters.datetime=datetime.datetime
        parameters.folder_for = lambda *args:self.folder
        self.cf = ModuleType('cf_posting.posting')
        self.cf.validate_basic_article = Mock(side_effect=lambda a:a if a.get('title') else (_ for _ in ()).throw(ValueError('Missing article field: title')))
        jobs = ModuleType('common.dashboard_jobs'); jobs.write=write; jobs.atomic_text=lambda p,s,**kw:p.write_text(s,encoding='utf-8')
        modules={'common':ModuleType('common'),'common.work_agenda':agendas,'common.channel_parameters':parameters,
                 'common.dashboard_jobs':jobs,'cf_posting':ModuleType('cf_posting'),'cf_posting.posting':self.cf}
        self.addCleanup(patch.stopall)
        patch.dict(sys.modules,modules).start(); patch.object(Path,'home',return_value=self.root).start()
        self.ns = functions('dashboard/common/conference_dispatch.py',['cf_recovery_original','cf_preparation_retry_guard','retry_active'], {
            'Path':Path,'ROOT':self.root,'QUEUE':self.queue,'load':lambda p:read(p) if p.exists() else {},
            'write':write,'locked':lambda p:nullcontext(),'hashlib':hashlib,'json':json,'re':re,'os':os,
            'time':SimpleNamespace(time=lambda:1000)})

    def test_original_hash_slot_action_and_history_survive_retry(self):
        result=self.ns['retry_active']()
        row=read(self.file)
        self.assertEqual(result['agendaId'],self.identity)
        self.assertEqual(row['arguments'],self.args)
        self.assertEqual(row['attempts'],2)
        self.assertEqual(row['status'],'queued')
        archived=Path(row['attemptHistory'][0]['terminalReceipt']['path'])
        self.assertEqual(read(archived),self.original)
        self.assertEqual(len(list(self.queue.glob('*.json'))),1)

    def test_missing_ambiguous_changed_or_wrong_owner_rejected(self):
        for kind in ('missing','ambiguous','changed','owner','slot'):
            with self.subTest(kind=kind):
                write(self.file,self.original)
                extra=self.queue/'extra.json'; extra.unlink(missing_ok=True)
                if kind=='missing':self.file.unlink()
                if kind=='ambiguous':write(extra,self.original)
                if kind=='changed':write(self.file,{**self.original,'arguments':{**self.args,'action':'cf'}})
                if kind=='owner':write(self.file,{**self.original,'businessAgendaId':'another'})
                if kind=='slot':write(self.file,{**self.original,'arguments':{**self.args,'slot':None}})
                with self.assertRaises(ValueError):self.ns['cf_recovery_original'](self.current)

    def test_unsafe_ledger_manual_auth_live_and_receipt_fence_retry(self):
        for kind in ('unknown','submitting','pending_effect','published','manual','auth','live','receipt','old_receipt'):
            with self.subTest(kind=kind):
                write(self.file,self.original)
                doc={'date':self.day,'items':[{'domain':'example.com','status':'waiting'}]}
                receipt=self.folder/'publication-receipt.json'; receipt.unlink(missing_ok=True)
                if kind in ('unknown','submitting','pending_effect','published'):doc['items'][0]['status']=kind
                if kind in ('manual','auth'):write(self.file,{**self.original,'failureReason':'manual_stop' if kind=='manual' else 'login_required'})
                if kind=='receipt':write(receipt,{'state':'submitting'})
                if kind=='old_receipt':
                    old=self.root/'cf_posting/output/old'; old.mkdir(exist_ok=True)
                    write(old/'publication-receipt.json',{'state':'accepted'});doc['items'][0]['artifactFolder']='output/old'
                write(self.schedule,doc)
                agendas=sys.modules['common.work_agenda']; agendas.running.return_value=[{'pid':-1}] if kind=='live' else []
                with self.assertRaises(ValueError):self.ns['retry_active']()
                self.assertEqual(read(self.file)['attempts'],1)

    def test_preparation_requires_explicit_proof_valid_input_and_remaining_budget(self):
        for override in ({'preparationOnly':False},{'submissionStarted':None},{'attempts':2}):
            with self.subTest(override=override):
                write(self.file,{**self.original,**override})
                with self.assertRaises(ValueError):self.ns['retry_active']()
        write(self.file,self.original);write(self.folder/'article.json',{})
        with self.assertRaisesRegex(ValueError,'Missing article'):self.ns['retry_active']()

    def test_receipt_appearing_before_locked_consumption_prevents_retry(self):
        class ReceiptBeforeLock:
            def __enter__(inner):write(self.folder/'publication-receipt.json',{'state':'submitting'})
            def __exit__(inner,*args):return False
        self.ns['locked']=lambda p:ReceiptBeforeLock()
        with self.assertRaisesRegex(ValueError,'requires reconciliation'):self.ns['retry_active']()
        self.assertEqual(read(self.file),self.original)


class CFEvidenceFreshness(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='cf-evidence-test-');self.addCleanup(self.temp.cleanup)
        self.folder=Path(self.temp.name)
        self.now=datetime.datetime(2026,11,3,12,tzinfo=datetime.timezone.utc)
        self.article={'mainKeyword':'approved topic','contentHtml':'medical condition'}
        self.research={'keyword':'approved topic','requestedKeyword':'approved topic','collectedAt':self.now.isoformat(),
                       'sources':[{'status':200,'text':'actual source','textSha256':hashlib.sha256(b'actual source').hexdigest()}]}
        quality=ModuleType('common.content_quality')
        ns=functions('dashboard/common/content_quality.py',['source_maximum_age','validate_research_freshness'], {
            'datetime':datetime.datetime,'timezone':datetime.timezone,'timedelta':datetime.timedelta,
            'MINIMUM_SOURCE_MAX_AGE':datetime.timedelta(hours=6),
            '_SENSITIVE':re.compile('medical'),'publication_text':lambda d:d['contentHtml']})
        quality.validate_research_freshness=lambda a,r:ns['validate_research_freshness'](a,r,now=self.now)
        self.quality=ns
        agendas=ModuleType('common.work_agenda');agendas.current=lambda:{'id':'owner','workTarget':{'arguments':{'action':'cf','account':'example.com'}}}
        self.addCleanup(patch.stopall)
        patch.dict(sys.modules,{'common':ModuleType('common'),'common.content_quality':quality,'common.work_agenda':agendas}).start()
        self.ns=functions('cf_posting/posting.py',['validate_cached_cf_evidence'],{'json':json,'re':re,'hashlib':hashlib,'os':os,'stamp':lambda:'now'})

    def save(self):
        write(self.folder/'research.json',self.research);write(self.folder/'article.json',self.article)

    def test_shared_ttl_boundary_future_time_and_24h_low_risk(self):
        for hours,allowed in [(6,True),(6.001,False),(-1,False)]:
            self.research['collectedAt']=(self.now-datetime.timedelta(hours=hours)).isoformat()
            if allowed:self.quality['validate_research_freshness'](self.article,self.research,now=self.now)
            else:
                with self.assertRaises(ValueError):self.quality['validate_research_freshness'](self.article,self.research,now=self.now)
        self.research['collectedAt']=(self.now-datetime.timedelta(hours=24)).isoformat()
        self.quality['validate_research_freshness']({'contentHtml':'ordinary'},self.research,now=self.now)

    def test_valid_cached_binding_passes_without_revision(self):
        self.save();self.ns['validate_cached_cf_evidence'](self.article,self.folder,'approved topic')
        self.assertFalse((self.folder/'evidence-refresh-request.json').exists())

    def test_stale_topic_or_source_hash_failure_creates_only_one_preserved_revision(self):
        self.research['keyword']='substituted topic';self.save()
        original=(self.folder/'research.json').read_bytes()
        for _ in range(2):
            with self.assertRaisesRegex(ValueError,'bounded repair revision'):
                self.ns['validate_cached_cf_evidence'](self.article,self.folder,'approved topic')
        request=read(self.folder/'evidence-refresh-request.json')
        self.assertEqual(request['revision'],1);self.assertEqual(request['maxAttempts'],1)
        self.assertEqual(request['attempts'],0)
        archive=self.folder/request['originals']['research.json']['path']
        self.assertEqual(archive.read_bytes(),original)
        self.assertEqual((self.folder/'research.json').read_bytes(),original)

    def test_receipt_prevents_any_refresh_revision(self):
        self.research['sources']=[];self.save();write(self.folder/'publication-receipt.json',{'state':'accepted'})
        with self.assertRaisesRegex(RuntimeError,'requires reconciliation'):
            self.ns['validate_cached_cf_evidence'](self.article,self.folder,'approved topic')
        self.assertFalse((self.folder/'evidence-refresh-request.json').exists())

    def test_stale_missing_source_and_changed_hash_each_hold(self):
        for kind in ('stale','missing','hash','article_topic'):
            with self.subTest(kind=kind):
                research=json.loads(json.dumps(self.research));article=dict(self.article)
                if kind=='stale':research['collectedAt']=(self.now-datetime.timedelta(hours=7)).isoformat()
                if kind=='missing':research['sources']=[]
                if kind=='hash':research['sources'][0]['text']='changed after collection'
                if kind=='article_topic':article['mainKeyword']='different topic'
                write(self.folder/'research.json',research)
                with self.assertRaisesRegex(ValueError,'bounded repair revision'):
                    self.ns['validate_cached_cf_evidence'](article,self.folder,'approved topic')


class CFPreparationAndQuery(unittest.TestCase):
    def test_overdue_preparation_does_not_take_publish_lock_or_publish(self):
        with tempfile.TemporaryDirectory(prefix='cf-prepare-test-') as temp:
            folder=Path(temp);(folder/'images').mkdir();(folder/'images/photo.png').write_bytes(b'image')
            article={'title':'Title','imagePlans':[{'filename':'photo.png'}]};write(folder/'article.json',article)
            day=datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9))).date().isoformat()
            cf=ModuleType('cf_posting.posting')
            cf.load_current_schedule=lambda:{'date':day,'items':[{'domain':'example.com','status':'waiting'}]}
            cf.basic_progress=Mock();cf.basic_article=Mock(return_value=article);cf.ensure_article_images=Mock(return_value=article)
            cf.slot_due=Mock(return_value=True);cf.cleaner_lock=Mock(side_effect=AssertionError('must not publish'));cf.run_basic_posting=Mock()
            agendas=ModuleType('common.work_agenda');agendas.enabled=lambda:False
            llm=ModuleType('common.llm_client');llm.generate_json=Mock(side_effect=AssertionError('no model'))
            assets=ModuleType('common.asset_map');assets.CF_DOMAINS={}
            modules={'common':ModuleType('common'),'common.work_agenda':agendas,'common.llm_client':llm,'common.asset_map':assets,
                     'cf_posting':ModuleType('cf_posting'),'cf_posting.posting':cf}
            ns=functions('dashboard/common/channel_parameters.py',['prepare_cf'],{
                'ROOT':folder,'policy':lambda:{'cf':{'example.com':'00:00'},'effectiveDate':day},
                'datetime':datetime.datetime,'KST':datetime.timezone(datetime.timedelta(hours=9)),
                'folder_for':lambda *args:folder,'load':lambda p:read(p) if p.exists() else {},'write':write,'hashlib':hashlib,'json':json})
            with patch.dict(sys.modules,modules):
                result=ns['prepare_cf'](day,'example.com',publish_if_due=False)
            self.assertEqual(result['state'],'prepared')
            self.assertTrue(result['preparationVerified'])
            cf.cleaner_lock.assert_not_called();cf.run_basic_posting.assert_not_called();llm.generate_json.assert_not_called()

    def test_exact_query_never_uses_substituting_synapse(self):
        with tempfile.TemporaryDirectory(prefix='cf-query-test-') as temp:
            folder=Path(temp)
            jobs=ModuleType('common.dashboard_jobs');jobs.write=write
            bridge=ModuleType('common.crew_chat_bridge');bridge.emit_work_event=Mock();bridge.work_task_id=lambda p:'test'
            synapse=ModuleType('dashboard.agents.synapse');synapse.research_query=Mock(return_value='unrelated topic')
            search=Mock(return_value=[{'url':'https://example.com/source'}]);fetch=Mock(return_value={'url':'https://example.com/source','text':'actual source '*30})
            ns=functions('dashboard/common/source_discovery.py',['research'],{
                'search_urls':search,'public_text':fetch,'requests':SimpleNamespace(RequestException=RuntimeError)})
            with patch.dict(sys.modules,{'common':ModuleType('common'),'common.dashboard_jobs':jobs,'common.crew_chat_bridge':bridge,'dashboard.agents.synapse':synapse}):
                ns['research']('approved topic',folder,exact_query=True)
            synapse.research_query.assert_not_called();search.assert_called_once_with('approved topic')
            result=read(folder/'research.json')
            self.assertEqual(result['keyword'],result['requestedKeyword'])


class CFAutomaticPreparationTiming(unittest.TestCase):
    def setUp(self):
        self.quality=ModuleType('common.content_quality');self.quality.MINIMUM_SOURCE_MAX_AGE=datetime.timedelta(hours=6)
        agendas=ModuleType('common.work_agenda');agendas.current=lambda:None;agendas.enabled=lambda:True
        agendas.STATE=Path('unused');agendas.autonomous_experiment_allows=Mock(return_value=True)
        self.addCleanup(patch.stopall)
        patch.dict(sys.modules,{'common':ModuleType('common'),'common.content_quality':self.quality,'common.work_agenda':agendas}).start()
        self.ns=functions('dashboard/common/conference_dispatch.py',['request','cf_preparation_window_open'],{})
        self.item={'action':'cf-prepare','account':'example.com','date':'2026-11-03','slot':'12:00'}

    def test_midnight_deferred_near_slot_and_due_catchup_allowed(self):
        zone=datetime.timezone(datetime.timedelta(hours=9))
        for hour,minute,allowed in [(0,0,False),(9,59,False),(10,0,True),(11,30,True),(12,0,True),(23,0,True)]:
            with self.subTest(hour=hour,minute=minute):
                self.assertEqual(self.ns['cf_preparation_window_open'](self.item,datetime.datetime(2026,11,3,hour,minute,tzinfo=zone)),allowed)
        self.assertFalse(self.ns['cf_preparation_window_open'](self.item,datetime.datetime(2026,11,4,0,tzinfo=zone)))

    def test_only_new_automatic_aggregate_preparation_is_deferred(self):
        enqueue=Mock(return_value={'status':'conference_requested'})
        self.ns.update(concrete_requests=lambda *args:[self.item],_existing_concrete_work=lambda *args:False,
                       _request_single=enqueue,cf_preparation_window_open=lambda item:False,load=lambda p:{})
        result=self.ns['request']('parameters',{'action':'cf-cycle'},automatic=True)
        self.assertEqual(result['reason'],'cf_preparation_window_waiting');enqueue.assert_not_called()
        self.ns['request']('parameters',{'action':'cf-cycle'},automatic=False)
        self.assertEqual(enqueue.call_count,1)
        self.ns['request']('parameters',self.item,automatic=True)
        self.assertEqual(enqueue.call_count,2)
        self.ns['_existing_concrete_work']=lambda *args:True
        self.ns['request']('parameters',{'action':'prepare'},automatic=True)
        self.assertEqual(enqueue.call_count,3)

    def test_published_and_receipt_preservation_never_become_new_automatic_work(self):
        with tempfile.TemporaryDirectory(prefix='cf-timing-filter-') as temp:
            folder=Path(temp)
            parameters=ModuleType('common.channel_parameters');parameters.KST=datetime.timezone(datetime.timedelta(hours=9))
            parameters.policy=lambda:{'cf':{'published.com':'00:00','receipt.com':'23:59'}}
            parameters.folder_for=lambda *args:folder
            cf=ModuleType('cf_posting.posting')
            cf.load_current_schedule=lambda:{'items':[{'domain':'published.com','status':'published'}, {'domain':'receipt.com','status':'waiting'}]}
            write(folder/'publication-receipt.json',{'state':'published','publicPublicationVerified':True})
            ns=functions('dashboard/common/conference_dispatch.py',['concrete_requests'],{'load':read})
            with patch.dict(sys.modules,{'common.channel_parameters':parameters,'cf_posting':ModuleType('cf_posting'),'cf_posting.posting':cf}):
                self.assertEqual(ns['concrete_requests']('parameters',{'action':'cf-cycle'}),[])


class ExactInsurerSource(unittest.TestCase):
    def test_only_reviewed_product_pdf_is_primary(self):
        ns=functions('dashboard/common/content_improvement.py',['primary_url'],{'urlparse':urlparse,'re':re,'PRIMARY_HOSTS':('gov.kr',)})
        url='https://m.samsungfire.com/download/product/P_P02_03_01_033_2.pdf'
        self.assertTrue(ns['primary_url'](url))
        for hostile in (url+'?x=1',url+'#page=12',url.replace('https:','http:'),url.replace('.com/','.com:444/'),
                        url.replace('https://','https://user@'),url.replace('.com/','.com.evil.com/'),
                        url.replace('/download/','/downloads/'),url.replace('_2.pdf','_3.pdf'),
                        url.replace('m.samsungfire.com','samsungfire.com'),url.replace('m.samsungfire.com','other.samsungfire.com')):
            with self.subTest(url=hostile):self.assertFalse(ns['primary_url'](hostile))


class CFRealModuleRouting(unittest.TestCase):
    def test_full_modules_defer_then_prepare_then_publish_at_original_kst_slot(self):
        """Real module entrypoints; only the external engine and state stores are fakes."""
        def load_module(name, relative):
            spec=importlib.util.spec_from_file_location(name,ROOT/relative)
            module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
            return module
        with tempfile.TemporaryDirectory(prefix='cf-routing-test-') as temp:
            root=Path(temp);folder=root/'draft';folder.mkdir();(folder/'images').mkdir()
            (folder/'images/photo.png').write_bytes(b'image')
            article={'title':'Approved topic','imagePlans':[{'filename':'photo.png'}]};write(folder/'article.json',article)
            zone=datetime.timezone(datetime.timedelta(hours=9))
            class Clock(datetime.datetime):
                instant=datetime.datetime(2026,11,3,0,tzinfo=zone)
                @classmethod
                def now(cls,tz=None):return cls.instant.astimezone(tz) if tz else cls.instant.replace(tzinfo=None)
            agendas=ModuleType('common.work_agenda');agendas.current=lambda:None;agendas.enabled=lambda:False
            agendas.STATE=root/'unused';agendas.autonomous_experiment_allows=lambda *a,**kw:True
            store=ModuleType('common.collection_observability');store.load=lambda p:read(p) if p.exists() else {};store.write=write;store.locked=lambda p:nullcontext()
            llm=ModuleType('common.llm_client');llm.generate_json=Mock(side_effect=AssertionError('live model forbidden'))
            assets=ModuleType('common.asset_map');assets.CF_DOMAINS={}
            cf=ModuleType('cf_posting.posting');cf.ALL_DOMAINS=['example.com'];cf.SCHEDULE_JSON=root/'schedule.json'
            schedule={'date':'2026-11-03','items':[{'domain':'example.com','status':'waiting','scheduledTime':'12:00'}]}
            cf.load_current_schedule=lambda:schedule;cf.basic_progress=Mock();cf.basic_article=Mock(return_value=article)
            cf.slot_due=lambda *a:True;cf.cleaner_lock=lambda **kw:nullcontext(True)
            def images(article,folder,**kwargs):write(folder/'photo-plan.json',{'prepared':True});return article
            cf.ensure_article_images=images
            cf.run_basic_posting=Mock(return_value={'state':'published','publicPublicationVerified':True,'publicUrl':'https://example.com/post'})
            modules={'common':ModuleType('common'),'common.work_agenda':agendas,'common.collection_observability':store,
                     'common.llm_client':llm,'common.asset_map':assets,'cf_posting':ModuleType('cf_posting'),'cf_posting.posting':cf}
            with patch.dict(sys.modules,modules),patch.object(sys,'path',list(sys.path)),patch.object(Path,'home',return_value=root), \
                 patch('requests.sessions.Session.request',side_effect=AssertionError('network forbidden')), \
                 patch('subprocess.Popen',side_effect=AssertionError('process forbidden')),patch('builtins.print'):
                quality=load_module('_cf_test_quality','dashboard/common/content_quality.py')
                parameters=load_module('_cf_test_parameters','dashboard/common/channel_parameters.py')
                with patch.dict(sys.modules,{'common.channel_parameters':parameters,'common.content_quality':quality}):
                    conference=load_module('_cf_test_conference','dashboard/common/conference_dispatch.py')
                    parameters.ROOT=root;parameters.datetime=Clock
                    parameters.policy=lambda:{'cf':{'example.com':'12:00'},'effectiveDate':'2026-11-03'}
                    parameters.folder_for=lambda *a:folder
                    parameters.planning_or_memory=lambda *a,**kw:{'keyword':'Approved topic','writingGuide':'Verified facts'}
                    conference._existing_concrete_work=lambda *a:False
                    enqueue=Mock(return_value={'status':'conference_requested'});conference._request_single=enqueue
                    with patch('datetime.datetime',Clock):
                        result=conference.request('parameters',{'action':'cf-cycle'},automatic=True)
                        self.assertEqual(result['reason'],'cf_preparation_window_waiting');enqueue.assert_not_called()
                        Clock.instant=datetime.datetime(2026,11,3,10,tzinfo=zone)
                        conference.request('parameters',{'action':'cf-cycle'},automatic=True)
                        original=enqueue.call_args.args[1]
                        self.assertEqual(original,{'action':'cf-prepare','date':'2026-11-03','account':'example.com','slot':'12:00'})
                        prepared=parameters.main(['cf-prepare','--date','2026-11-03','--account','example.com','--slot','12:00'],conference_worker=True)
                        self.assertEqual(prepared['state'],'prepared');cf.run_basic_posting.assert_not_called()
                        Clock.instant=datetime.datetime(2026,11,3,12,tzinfo=zone)
                        conference.request('parameters',{'action':'cf-cycle'},automatic=True)
                        publish=enqueue.call_args.args[1]
                        self.assertEqual(publish,{**original,'action':'cf'})
                        parameters.main(['cf','--date','2026-11-03','--account','example.com','--slot','12:00'],conference_worker=True)
                        cf.run_basic_posting.assert_called_once_with('example.com',folder)


if __name__ == '__main__':
    unittest.main()
