import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from common import operating_plan as operating
from common.collection_observability import load, write


class OperatingPlanTests(unittest.TestCase):
    def test_prepared_input_ownership_and_blocker_survive_in_manager_board(self):
        write(self.data/'cafe/status.json',{'publishedArticles':[{'part':22}]})
        write(self.data/'cafe/preparation-jobs.json',{'jobs':{'boutiqueinfo:23':{
            'project':'naver_cafe','part':23,'cafeId':'boutiqueinfo','status':'needs_attention','reason':'source_capture_required'}}})
        write(self.data/'youtube/preparation-jobs.json',{'jobs':{'a'*64:{'channelHandle':'@owned',
            'status':'needs_attention','result':{'reason':'account_space_control_required'}}}})
        board=operating.execution_board(self.now.timestamp())
        prepare=next(r for r in board['work'] if r['id']=='prepare:naver_cafe')
        self.assertEqual(prepare['suggestedUnpublishedPart'],24)
        youtube=next(r for r in board['work'] if r['id'].startswith('youtube-input:'))
        self.assertEqual(youtube['reason'],'account_space_control_required');self.assertEqual(youtube['owner'],'patch')
        self.assertFalse(youtube['autoRetry'])

    def test_business_brief_exposes_missing_sources_without_fabricating_article_earnings(self):
        revenue={'collectionStatus':'partial','months':{'2026-11':{'sources':[
            {'id':'adsense','status':'collected','currency':'USD','checkedAt':self.now.isoformat(),'daily':{'2026-11-07':'0.02'}},
            {'id':'adpost','status':'auth_required','currency':'KRW','daily':{}}]}},
            'growth':{'windows':{'recent':{'start':'2026-11-01','end':'2026-11-07'}},'sources':{'sj':{
                'currency':'USD','timezone':'America/Los_Angeles','rows':[
                    {'date':'2026-11-06','domain':'daynote.kr','revenue':'0.02','pageViews':10},
                    {'date':'2026-11-06','domain':'daynote.kr','revenue':'0.02','pageViews':10}]}}},
            'pagePerformance':{'complete':False,'pages':[]}}
        brief=operating.business_brief(revenue,{'pagePerformance':{'pages':[{'url':'https://example.com/a','sessions':3}]}},self.now.timestamp())
        self.assertIsNone(brief['revenueSources'][1]['todayAmount'])
        self.assertEqual(brief['measurementBlockers'][0]['id'],'adpost')
        measured=brief['domainRevenueWindows'][0]
        self.assertEqual(measured['observedDomains'][0]['amount'],0.02)
        self.assertEqual(measured['duplicateRowsExcluded'],1)
        self.assertNotIn('revenue',brief['trafficCandidates'][0])
        self.assertFalse(brief['pageRevenueCoverage']['complete'])

    def test_future_prepared_allocation_waits_then_becomes_dispatchable_without_repair(self):
        from cf_posting import posting as cf
        base=patch.object(cf,'BASE_DIR',self.root/'cf_posting');base.start();self.addCleanup(base.stop)
        key=self.allocate([self.allocation('cf_blog','daynote.kr',hour=11)])['allocationIds'][0]
        folder=self.root/'cf_posting/output/future'
        write(folder/'article.json',{'title':'Reader task'});write(folder/'photo-plan.json',{})
        write(self.data/'cf/daily_schedule.json',{'date':'2026-11-07','items':[
            {'domain':'daynote.kr','status':'waiting','allocationId':key,'artifactFolder':'output/future','scheduledTime':'11:00'}]})
        before=operating.execution_board(self.now.timestamp())
        row=next(r for r in before['work'] if r['id']=='allocation:'+key)
        self.assertEqual(row['state'],'waiting_schedule');self.assertIsNone(row['dispatch'])
        after=operating.execution_board(self.now.replace(hour=11).timestamp())
        row=next(r for r in after['work'] if r['id']=='allocation:'+key)
        self.assertIsNotNone(row['dispatch']);self.assertNotEqual(before['fingerprint'],after['fingerprint'])

    def test_board_exposes_business_without_resource_counters_self_waking_manager(self):
        write(self.data/'revenue.json',{'collectionStatus':'partial','months':{}})
        with patch('common.llm_usage.resource_summary',return_value={'modelCalls':1}):
            first=operating.execution_board(self.now.timestamp())
        with patch('common.llm_usage.resource_summary',return_value={'modelCalls':2}):
            second=operating.execution_board(self.now.timestamp())
        self.assertEqual(first['fingerprint'],second['fingerprint'])
        self.assertEqual(second['business']['resourceUse']['modelCalls'],2)
        self.assertEqual(second['business']['collectionStatus'],'partial')

    def test_unallocated_time_can_be_assigned_and_exact_prepared_asset_is_reused(self):
        from cf_posting import posting as cf
        from contextlib import nullcontext
        original=self.root/'cf_posting/output/normalization/2026-11-07/daynote.kr/reviewed'
        write(original/'article.json',{'title':'Existing reviewed reader task'})
        raw=(original/'article.json').read_bytes()
        schedule={'date':'2026-11-07','items':[{'domain':'daynote.kr','scheduledTime':'09:00','status':'unallocated'}]}
        write(self.data/'cf/daily_schedule.json',schedule)
        allocated=self.allocate([{'project':'cf_blog','account':'daynote.kr','publishAt':self.now.replace(hour=9).isoformat(),
                                 'topic':'Existing reviewed reader task','why':'Use an unpublished reviewed asset'}])
        self.assertNotEqual(next(iter(load(operating.STATE)['publications'].values()))['status'],'conflict_existing_work')
        asset={'folder':str(original),'topic':'Existing reviewed reader task','title':'Existing reviewed reader task','articleSha256':'bound-sha'}
        with patch.object(cf,'BASE_DIR',self.root/'cf_posting'),patch.object(cf,'SCHEDULE_JSON',self.data/'cf/daily_schedule.json'), \
             patch.object(cf,'cleaner_lock',return_value=nullcontext(True)),patch.object(cf,'load_current_schedule',return_value=schedule), \
             patch.object(cf,'save_schedule_file',side_effect=write),patch.object(operating,'prepared_cf_asset',return_value=asset):
            self.assertTrue(operating.activate_cf(self.now))
        item=load(self.data/'cf/daily_schedule.json')['items'][0]
        self.assertEqual((self.root/'cf_posting'/item['artifactFolder']).resolve(),original.resolve())
        self.assertEqual(item['preparedFrom']['articleSha256'],'bound-sha')
        self.assertEqual((original/'article.json').read_bytes(),raw)

    def test_cafe_enters_review_inventory_only_with_exact_document_and_public_receipt(self):
        from naver_cafe_posting.editorial import digest
        folder=self.root/'naver_cafe_posting/output/prepared/part-22/boutiqueinfo'
        document={'title':'Verified reader task'};sha=digest(document);url='https://cafe.naver.com/example/2522'
        write(self.data/'cafe/status.json',{'publishedArticles':[{'part':22,'cafeId':'boutiqueinfo',
            'account':'soul5373','articleUrl':url,'status':'published_verified','publicState':'body_verified'}]})
        self.assertEqual(operating.publication_inventory(),[])
        write(folder/'document.json',document)
        write(folder/'prepared.json',{'cafeId':'boutiqueinfo','documentSha256':sha})
        for name in ('intent.json','public-evidence.json'):
            write(folder/name,{'status':'verified_published','url':url,'documentSha256':sha})
        inventory=operating.publication_inventory()
        self.assertEqual(inventory[0]['project'],'naver_cafe')
        self.assertTrue(inventory[0]['publicBodyMatched'])
        write(folder/'document.json',{'title':'Changed after receipt'})
        self.assertEqual(operating.publication_inventory(),[])

    def test_execution_board_ignores_poll_clocks_but_wakes_for_receipt_facts(self):
        self.allocate([self.allocation()])
        write(self.data/'revenue.json',{'updatedAt':1,'daily':{'amount':None}})
        one=operating.execution_board(self.now.timestamp())
        write(self.data/'revenue.json',{'updatedAt':2,'daily':{'amount':None}})
        two=operating.execution_board(self.now.timestamp()+1)
        self.assertEqual(one['fingerprint'],two['fingerprint'])
        write(self.data/'revenue.json',{'updatedAt':3,'daily':{'amount':5}})
        self.assertNotEqual(two['fingerprint'],operating.execution_board(self.now.timestamp()+2)['fingerprint'])
        expired=operating.execution_board((self.now+timedelta(days=1)).timestamp())
        item=next(r for r in expired['work'] if r['id'].startswith('allocation:'))
        self.assertIsNone(item['dispatch'])
        self.assertFalse(expired['publicationVerified'])

    def test_execution_board_preserves_protected_brunch_and_staff_intents(self):
        folder=self.root/'brunch_posting/output/prepared/part-13'
        write(folder/'article.json',{'part':13,'title':'exact draft'})
        write(folder/'publication-intent.json',{'state':'unknown'})
        receipt=self.data/'chats/staff-requests'/('a'*64+'.json')
        write(receipt,{'status':'held','reasonCode':'budget_exhausted','results':[]})
        write(operating.STATE,{'actions':{'owned':{'receiptPath':str(receipt),'action':{'agent':'publi','args':{'project':'brunch'}}}}})
        before=receipt.read_bytes()
        board=operating.execution_board(self.now.timestamp())
        protected=[r for r in board['work'] if r['id'] in ('brunch-part:13','staff:owned')]
        self.assertEqual(len(protected),2)
        self.assertTrue(all(r['state']=='protected_hold' and r['dispatch'] is None for r in protected))
        self.assertEqual(receipt.read_bytes(),before)

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.data=self.root/'dashboard/data';self.data.mkdir(parents=True)
        self.now=datetime(2026,11,7,8,tzinfo=operating.KST)
        write(self.data/'daily_schedule.json',{'operatingMode':'adaptive','naver':{'soul5373':{'slots':['10:30','19:30']}},'cf':{'daynote.kr':'09:00'}})
        p=patch('common.llm_usage.ROOT',self.root);p.start();self.addCleanup(p.stop)
        for key,value in [('ROOT',self.root),('DATA',self.data),('STATE',self.data/'operating-plan.json')]:
            p=patch.object(operating,key,value);p.start();self.addCleanup(p.stop)

    def allocation(self,project='naver_blog',account='soul5373',hour=11):
        return {'project':project,'account':account,'publishAt':self.now.replace(hour=hour).isoformat(),
                'topic':'distinct reader question '+str(hour),'why':'Explore measured demand and current account reach'}

    def allocate(self,rows):
        return operating.allocate({'publications':rows},now=self.now.timestamp(),goal_id='test')

    def test_adaptive_mode_removes_internal_count_caps_without_changing_real_counts(self):
        self.assertFalse(operating.cap_reached(1000,10))
        self.assertIsNone(operating.remaining(1000,10))
        write(self.data/'daily_schedule.json',{})
        self.assertTrue(operating.cap_reached(10,10))

    def test_more_than_two_naver_slots_are_executable_and_idempotent(self):
        rows=[self.allocation(hour=h) for h in range(11,19)]
        first=self.allocate(rows);self.allocate(rows)
        plan={'soul5373':{'slots':['10:30','19:30']}}
        slots=operating.naver_slots(plan,'2026-11-07')['soul5373']['slots']
        self.assertEqual(len(slots),10)
        self.assertEqual(len(load(operating.STATE)['publications']),8)
        self.assertFalse(first['publicationVerified'])
        self.assertEqual(plan['soul5373']['slots'],['10:30','19:30'])

    def test_future_day_does_not_recreate_a_fixed_two_post_requirement(self):
        policy=load(self.data/'daily_schedule.json');policy['legacySlotsCarryThrough']='2026-11-07';write(self.data/'daily_schedule.json',policy)
        plan={'soul5373':{'slots':['10:30','19:30']}}
        self.assertEqual(operating.naver_slots(plan,'2026-11-08')['soul5373']['slots'],[])
        write(self.data/'naver/automation-journal.json',{'attempts':[{'account':'soul5373','reserveTime':'2026-11-08 10:30','scheduledSlot':'10:30','phase':'verified'}]})
        self.assertEqual(operating.naver_slots(plan,'2026-11-08')['soul5373']['slots'],['10:30'])

    def test_new_cf_day_has_no_one_post_per_domain_requirement(self):
        from cf_posting import posting as cf
        path=self.data/'cf/daily_schedule.json'
        with patch.object(cf,'SCHEDULE_JSON',path),patch.object(cf,'ALL_DOMAINS',['daynote.kr']),patch.object(cf,'save_schedule_file'):
            result=cf.load_current_schedule()
        self.assertEqual(result['items'][0]['status'],'unallocated')
        self.assertFalse(cf.slot_due(result['items'][0],self.now))

    def test_allocation_rejects_backdating_unknown_accounts_and_identity_changes(self):
        row=self.allocation();self.allocate([row])
        for invalid in ({**row,'account':'unknown'},{**row,'publishAt':self.now.isoformat()},
                        {**row,'topic':'replace an existing assignment'}):
            with self.assertRaises(ValueError):self.allocate([invalid])
        self.assertEqual(len(load(operating.STATE)['publications']),1)

    def test_existing_commitment_returns_conflict_instead_of_claiming_extra_volume(self):
        policy=load(self.data/'daily_schedule.json');policy['legacySlotsCarryThrough']='2026-11-07';write(self.data/'daily_schedule.json',policy)
        row=self.allocation();row['publishAt']=self.now.replace(hour=10,minute=30).isoformat()
        result=self.allocate([row])
        self.assertFalse(result['ok'])
        self.assertEqual(result['status'],'allocation_conflict')
        self.assertEqual(result['allocationIds'],[])
        self.assertEqual(operating.allocations('naver_blog'),[])

    def test_account_pause_is_owned_and_expires_for_reassessment(self):
        operating.allocate({'accounts':[{'project':'naver_blog','account':'soul5373','mode':'pause',
            'why':'Observed issue needs diagnosis','reviewAt':(self.now+timedelta(hours=2)).isoformat()}]},now=self.now.timestamp())
        self.assertFalse(operating.account_available('naver_blog','soul5373',self.now.timestamp()))
        self.assertTrue(operating.account_available('naver_blog','soul5373',(self.now+timedelta(hours=3)).timestamp()))
        self.assertEqual(operating.context((self.now+timedelta(hours=3)).timestamp())['accountReviewsDue'],['naver_blog:soul5373'])

    def test_cf_next_same_day_article_preserves_receipt_history_and_separate_folder(self):
        from cf_posting import posting as cf
        from contextlib import contextmanager
        @contextmanager
        def acquired():yield True
        base=self.root/'cf_posting';folder=base/'output/scheduled/2026-11-07/daynote.kr';folder.mkdir(parents=True)
        write(folder/'publication-receipt.json',{'state':'published','publicPublicationVerified':True,
            'publicUrl':'https://www.daynote.kr/first'})
        schedule={'date':'2026-11-07','items':[{'domain':'daynote.kr','status':'published','publicUrl':'https://www.daynote.kr/first','scheduledTime':'09:00'}]}
        original=json.loads(json.dumps(schedule))
        self.allocate([self.allocation('cf_blog','daynote.kr',hour=12),self.allocation('cf_blog','daynote.kr',hour=16)])
        with patch.object(cf,'BASE_DIR',base),patch.object(cf,'cleaner_lock',acquired), \
             patch.object(cf,'load_current_schedule',return_value=schedule),patch.object(cf,'save_schedule_file') as save:
            self.assertTrue(operating.activate_cf(self.now))
            item=schedule['items'][0]
            self.assertEqual(item['publicationHistory'],original['items'])
            self.assertEqual(item['scheduledTime'],'12:00')
            self.assertIn('daynote.kr-1200-',item['artifactFolder'])
            self.assertFalse(operating.activate_cf(self.now))
            save.assert_called_once()
        self.assertEqual(load(folder/'publication-receipt.json')['publicUrl'],'https://www.daynote.kr/first')

    def test_cf_uncertain_submission_is_never_rotated_into_new_work(self):
        from cf_posting import posting as cf
        from contextlib import contextmanager
        @contextmanager
        def acquired():yield True
        self.allocate([self.allocation('cf_blog','daynote.kr',hour=12)])
        schedule={'date':'2026-11-07','items':[{'domain':'daynote.kr','status':'submission_unknown'}]}
        with patch.object(cf,'cleaner_lock',acquired),patch.object(cf,'load_current_schedule',return_value=schedule),patch.object(cf,'save_schedule_file') as save:
            self.assertFalse(operating.activate_cf(self.now));save.assert_not_called()

    def test_every_verified_naver_url_becomes_owned_followup_without_faking_metrics(self):
        url='https://blog.naver.com/mustinfo/123'
        write(self.data/'naver/public-verification.json',{'evidence':[{'publicUrl':url,'account':'soul5373',
            'publicPublicationVerified':True,'publicBodyMatched':True}]})
        self.assertEqual(operating.context()['publicationsNeedingReview'][0]['url'],url)
        result=operating.review_publication({'url':url,'assessment':'Body matched; search/revenue unmeasured',
            'nextAction':'Collect URL-scoped search visits','nextReviewAt':(datetime.now(operating.KST)+timedelta(days=7)).isoformat(),
            'evidenceIds':['e0']},goal_id='manager')
        self.assertFalse(result['businessOutcomeVerified'])
        self.assertEqual(operating.context()['publicationsNeedingReview'],[])
        self.assertEqual(load(operating.STATE)['reviews'][url]['owner'],'jarvis')

    def test_company_manager_uses_continuing_loop_independent_of_waiting_experiment(self):
        from agents import crew_reasoning as crew
        write(self.data/'active-agenda.json',{'activeExperiment':{'status':'active','interventionReceipt':None,'maxModelCalls':20}})
        company={'projects':[{'id':'naver_blog','status':'attention','failures':[{'reason':'missing_supply'}]}]}
        with patch.object(crew,'reason_request',return_value={'id':'a'*64,'status':'ready'}) as create:
            self.assertTrue(operating.check_once(company,self.now.timestamp()))
            args=create.call_args.kwargs
            self.assertTrue(args['execute']);self.assertTrue(args['repair'])
            self.assertEqual(args['origin'],'company-manager')
        self.assertEqual(load(self.data/'active-agenda.json')['activeExperiment']['maxModelCalls'],20)

    def test_large_manager_snapshot_does_not_drop_last_project_or_operating_tools(self):
        from agents import crew_reasoning as crew
        snapshot={'projects':[{'id':'first','detail':'x'*6000},{'id':'last','blocker':'missing_input'}],
                  'operatingContext':{'publicationQuotas':None,'detailReaders':{'plan':'operating_plan'}}}
        row={'observations':[{'id':'e0','actor':'host','tool':'projects','arguments':{},'observedAt':1,'sha256':'test','result':snapshot}]}
        result=crew.prompt_observations(row)[0]['result']
        self.assertEqual(result['projects'][-1]['blocker'],'missing_input')
        self.assertIsNone(result['operatingContext']['publicationQuotas'])
        self.assertNotIn('truncated',result)

    def test_portfolio_manager_is_not_given_single_publication_instructions(self):
        from agents import crew_reasoning as crew
        row={'id':'a'*64,'actor':'jarvis','origin':'company-manager','goal':'Grow company revenue',
            'permissions':{'execute':True,'repair':True,'projects':['naver_blog']},'observations':[], 'decisions':0}
        with patch('common.llm_client.generate_json',side_effect=RuntimeError('test stop')) as model:
            with self.assertRaisesRegex(RuntimeError,'test stop'):crew.ask(row)
        prompt=model.call_args.args[0]
        self.assertNotIn('Business work follows one active agenda',prompt)
        self.assertIn('allocate_publications',prompt)
        self.assertIn('ownedOperatingActions',prompt)
        self.assertIn('executionBoard',prompt)
        self.assertIn('Assess executionBoard.business',prompt)
        self.assertIn('For revenue questions inspect revenue/traffic/metrics',prompt)
        self.assertIn('why this action outranks alternatives',prompt)
        self.assertLess(len(prompt),40000)

    def test_manager_keeps_other_decisions_runnable_while_publication_executes(self):
        from agents import crew_reasoning as crew
        from server import agent_tools as tools
        row={'id':'a'*64,'origin':'company-manager','actor':'jarvis','goal':'Grow revenue',
            'permissions':{'execute':True,'repair':True,'projects':['naver_blog']},'observations':[]}
        action={'agent':'publi','tool':'run_project_cycle','args':{'project':'naver_blog'}}
        with patch.object(tools,'enqueue_staff_request',return_value={'taskId':'test','status':'queued'}),patch.object(crew,'save'):
            result=crew.tool_call(row,'dispatch',action)
        self.assertEqual(row['status'],'ready')
        self.assertNotIn('pendingAction',row)
        self.assertFalse(result['publicationVerified'])
        self.assertEqual(len(load(operating.STATE)['actions']),1)
        with self.assertRaisesRegex(ValueError,'already executed'):
            with patch.object(crew,'save'):crew.tool_call(row,'dispatch',action)

    def test_manager_recovers_same_enqueue_without_waiting_for_worker_completion(self):
        from agents import crew_reasoning as crew
        from server import agent_tools as tools
        row={'id':'a'*64,'origin':'company-manager','actor':'jarvis','observations':[],
             'status':'blocked','pendingAction':{'requestId':'same-original-request','enqueueFailures':3,
             'action':{'agent':'publi','tool':'prepare_cafe_content','args':{'project':'naver_cafe'}}}}
        with patch.object(tools,'STAFF_REQUEST_DIR',self.data/'staff'), \
             patch.object(tools,'enqueue_staff_request',return_value={'taskId':'same-task','status':'queued'}) as enqueue,patch.object(crew,'save'):
            self.assertTrue(crew.refresh_pending(row))
        self.assertEqual(row['status'],'ready')
        self.assertNotIn('pendingAction',row)
        self.assertEqual(row['operatingActions'][0]['requestId'],'same-original-request')
        self.assertEqual(enqueue.call_args.args[0],'same-original-request')
    def test_latest_paged_evidence_keeps_its_structured_missingness(self):
        from agents import crew_reasoning as crew
        source={'data':{'detail':'x'*13000,'revenue':None},'pagination':{'truncated':False},'sha256':'source'}
        row={'observations':[{'id':'e1','actor':'jarvis','tool':'evidence_batch','arguments':{},'observedAt':1,'sha256':'test','result':{'revenue':source}}]}
        result=crew.prompt_observations(row)[0]['result']['revenue']
        self.assertIsNone(result['data']['revenue'])
        self.assertEqual(result['sha256'],'source')

    def test_related_questions_and_manager_topics_are_not_overruled_by_fixed_heuristics(self):
        from common import asset_map as assets
        first='robot vacuum drain hose replacement'
        next_question='robot vacuum drain hose rental home installation'
        self.assertFalse(assets.is_duplicate_naver_topic(next_question,[first]))
        self.assertTrue(assets.is_duplicate_naver_topic(first,[first]))
        with patch.object(assets,'query_naver_blog_doc_count',side_effect=AssertionError('fixed-count admission should not run')):
            self.assertEqual(assets.select_verified_cf_keyword('daynote.kr',next_question),next_question)

    def test_full_asset_registry_contains_all_domains_and_yoon_shopping_capability(self):
        from common import asset_map as assets
        registry=assets.corporate_assets(self.root)
        self.assertEqual(set(registry['cfDomains']),set(assets.CF_DOMAINS))
        self.assertEqual(len(registry['naverAccounts']),5)
        self.assertIn('shopping_connect',registry['naverAccounts']['yoon_master']['monetization'])
        self.assertIn('adpost',registry['naverAccounts']['yoon_master']['monetization'])
        self.assertIn('shopping_connect',registry['affiliatePrograms'])
        self.assertEqual(registry['naverAccounts']['yoon_master']['shoppingConnectTools']['readEvidence'],
                         'evidence {name:shopping_connect}')
        self.assertIn('ShoppingConnect',assets.match_monetization_options('appliances',channel='yoon_master')['primaryEngine'])

    def test_staff_receipt_has_a_named_reader_instead_of_requiring_private_source_access(self):
        from agents import crew_reasoning as crew
        from server import agent_tools as tools
        folder=self.data/'chats/staff-requests';folder.mkdir(parents=True)
        identity='b'*64;write(folder/(identity+'.json'),{'status':'queued','results':[]})
        with patch.object(tools,'STAFF_REQUEST_DIR',folder),patch.object(crew,'ROOT',self.root):
            result=crew.read_evidence({'name':'staff_request:'+identity})
        self.assertEqual(result['data']['status'],'queued')
        self.assertTrue(result['available'])

    def test_scheduler_request_runs_despite_occupied_publication_lane_and_returns_evidence(self):
        from common import work_agenda as agendas
        from agents import crew_reasoning as crew
        from server import agent_tools as tools
        import hashlib
        rows=self.data/'publication-conferences/operations';rows.mkdir(parents=True)
        requests=self.data/'chats/staff-requests';requests.mkdir(parents=True)
        state=self.data/'active-agenda.json'
        busy='a'*64
        write(state,{'enabled':True,'activeIds':[busy],'activeId':busy,'pending':[]})
        write(rows/(busy+'.json'),{'id':busy,'kind':'conference','project':'naver_blog','status':'executing'})
        request='test-manager-cycle'
        action={'agent':'publi','tool':'run_project_cycle','args':{'project':'naver_blog'}}
        with patch.object(agendas,'DATA',self.data),patch.object(agendas,'ROWS',rows),patch.object(agendas,'STATE',state), \
             patch.object(agendas,'LANE_LIMITS',{'naver_blog':1}),patch.object(agendas,'running',return_value=[]), \
             patch.object(tools,'STAFF_REQUEST_DIR',requests),patch.object(tools,'BASE_DIR',self.root), \
             patch('common.crew_chat_bridge.emit_work_event',return_value='event'), \
             patch('common.ego_executor.execute_staff_action',return_value={'ok':True,'status':'observed','reservationVerified':True}) as execute:
            receipt=tools.enqueue_staff_request(request,[action])
            self.assertIsNotNone(agendas.admit(receipt['businessAgendaId']))
            agenda=agendas.get(receipt['businessAgendaId'])
            self.assertEqual(agendas.execution_lane(agenda),'scheduler')
            self.assertFalse(tools.process_staff_request_once())
            path=requests/(hashlib.sha256(request.encode()).hexdigest()+'.json')
            self.assertEqual(load(path)['executionWait']['reason'],'opening_delivery_pending')
            agendas.record_plan(agenda['id'],['Run registered scheduler and observe exact receipt'])
            agenda=agendas.get(agenda['id'])
            agendas.acknowledge(agenda['id'],'opening',agenda['events']['opening']['id'])
            self.assertTrue(tools.process_staff_request_once())
            self.assertEqual(load(path)['status'],'completed')
            self.assertNotIn('executionWait',load(path))
            self.assertFalse(tools.process_staff_request_once())
            execute.assert_called_once()
            manager={'operatingActions':[{'requestId':request,'receiptPath':str(path),'status':'queued'}],'observations':[]}
            with patch.object(crew,'save'):
                crew.refresh_operating_actions(manager)
            self.assertEqual(manager['executed'][request],'completed')
            self.assertTrue(manager['observations'][-1]['result']['results'][0]['result']['reservationVerified'])
            self.assertFalse(manager['observations'][-1]['result']['results'][0]['result'].get('publicationVerified',False))

    def test_parked_account_failure_does_not_own_other_accounts_but_live_process_still_counts(self):
        from common import work_agenda as agendas
        old={'kind':'conference','source':{'arguments':{'account':'soul5373'}}}
        other={'kind':'conference','source':{'arguments':{'account':'yoon_master'}}}
        with patch.object(agendas,'running',return_value=[]):
            self.assertFalse(agendas.shares_execution_lane(old,other))
            self.assertTrue(agendas.shares_execution_lane(old,old))
            self.assertTrue(agendas.shares_execution_lane({'kind':'goal'},other))
        with patch.object(agendas,'running',return_value=[{'pid':123}]):
            self.assertTrue(agendas.shares_execution_lane(old,other))

    def test_allocation_reports_exact_native_state_without_mistaking_reservation_for_publication(self):
        import hashlib
        row=self.allocation();self.allocate([row]);row=next(iter(load(operating.STATE)['publications'].values()))
        self.assertEqual(operating.allocation_execution(row)['status'],'not_dispatched')
        args={'action':'naver','date':row['day'],'account':row['account'],'slot':row['slot']}
        key=hashlib.sha256(json.dumps(['parameters',args],sort_keys=True).encode()).hexdigest()
        path=self.data/'publication-conferences'/(key+'.json')
        write(path,{'kind':'parameters','arguments':args,'status':'completed','outcomes':[{'reservationVerified':True}]})
        result=operating.allocation_execution(row)
        self.assertEqual(result['status'],'reserved_verified');self.assertFalse(result['publicationVerified'])
        write(path,{'kind':'parameters','arguments':{**args,'account':'another-account'},'status':'completed','outcomes':[{'publicationVerified':True}]})
        result=operating.allocation_execution(row)
        self.assertEqual(result['status'],'unknown');self.assertFalse(result['publicationVerified'])

    def test_browser_dispatch_routes_to_native_owner_and_preserves_repair_permissions(self):
        from agents import crew_reasoning as crew
        row={'actor':'jarvis','permissions':{'repair':True}}
        action={'agent':'jarvis','tool':'browser_ego_action','args':{'port':9335,'goal':'Inspect existing page','url':'https://example.com/'}}
        with patch.object(crew,'browser_ego_action',return_value={'status':'observed'}) as run:
            self.assertEqual(crew.tool_call(row,'dispatch',action)['status'],'observed')
            self.assertEqual(crew.tool_call(row,'browser_ego_action',action['args'])['status'],'observed')
        self.assertEqual(run.call_args.args[0]['actor'],'patch')
        row['permissions']['repair']=False
        with self.assertRaisesRegex(ValueError,'repair permission'):crew.tool_call(row,'dispatch',action)

    def test_cycle_skips_failed_work_and_requests_one_exact_child_without_parent_lock(self):
        from common import project_autonomy as autonomy,conference_dispatch as conferences,work_agenda as agendas
        import hashlib
        config=self.data/'project-autonomy.json';write(config,{'enabled':True,'projects':['naver_blog']})
        queue=self.data/'publication-conferences';queue.mkdir()
        old={'action':'naver','account':'soul5373','date':'2026-11-07','slot':'10:30'}
        new={**old,'slot':'11:30'}
        key=hashlib.sha256(json.dumps(['parameters',old],sort_keys=True).encode()).hexdigest()
        write(queue/(key+'.json'),{'status':'failed','failureReason':'manual_stop'})
        def request(kind,args,**kwargs):
            self.assertIsNone(agendas.current())
            self.assertEqual(args,new);self.assertFalse(kwargs['automatic'])
            return {'agendaId':'c'*64,'requestedAt':12}
        with patch.object(autonomy,'CONFIG',config),patch.object(agendas,'enabled',return_value=False), \
             patch.object(conferences,'QUEUE',queue),patch.object(conferences,'concrete_requests',return_value=[old,new]), \
             patch.object(conferences,'request',side_effect=request) as submit:
            result=autonomy.run_project_cycle('naver_blog')
        submit.assert_called_once()
        self.assertEqual(result['status'],'awaiting_completion');self.assertFalse(result['publicationVerified'])
        self.assertEqual(load(queue/(key+'.json'))['status'],'failed')

    def test_cycle_observes_existing_child_without_rebinding_or_replaying(self):
        from common import project_autonomy as autonomy,conference_dispatch as conferences,work_agenda as agendas
        import hashlib
        config=self.data/'project-autonomy.json';write(config,{'enabled':True,'projects':['naver_blog']})
        queue=self.data/'publication-conferences';queue.mkdir()
        args={'action':'naver','account':'soul5373','date':'2026-11-07','slot':'11:30'}
        key=hashlib.sha256(json.dumps(['parameters',args],sort_keys=True).encode()).hexdigest()
        original={'status':'running','businessAgendaId':'original-owner','requestedAt':123}
        write(queue/(key+'.json'),original)
        with patch.object(autonomy,'CONFIG',config),patch.object(agendas,'enabled',return_value=False), \
             patch.object(conferences,'QUEUE',queue),patch.object(conferences,'concrete_requests',return_value=[args]), \
             patch.object(conferences,'request') as submit:
            result=autonomy.run_project_cycle('naver_blog')
        submit.assert_not_called()
        self.assertEqual(result['conferenceAgendaId'],key)
        self.assertEqual(load(queue/(key+'.json')),original)

    def test_cf_preparation_receipt_is_observed_without_becoming_publication_or_retrying_unknown_work(self):
        from common import project_autonomy as autonomy,conference_dispatch as conferences,work_agenda as agendas
        from server import agent_tools as tools
        queue=self.data/'publication-conferences';queue.mkdir()
        key='d'*64;path=queue/(key+'.json')
        write(path,{'agendaId':key,'kind':'parameters','requestedAt':123,'status':'running','arguments':{'action':'cf-prepare'}})
        result={'status':'awaiting_completion','project':'cf_blog','conferenceAgendaId':key,'conferenceRequestedAt':123}
        requests=self.data/'chats/staff-requests';requests.mkdir(parents=True)
        request=requests/'request.json'
        write(request,{'status':'unknown','reason':'invalid_controller_receipt_no_retry',
            'results':[{'tool':'run_project_cycle','result':result}]})
        write(requests/'aaa-queued.json',{'status':'queued','actions':[{'agent':'publi','tool':'run_project_cycle','args':{'project':'naver_blog'}}]})
        with patch.object(conferences,'QUEUE',queue),patch.object(tools,'STAFF_REQUEST_DIR',requests),patch.object(tools,'BASE_DIR',self.root), \
             patch.object(agendas,'enabled',return_value=False),patch('common.ego_executor.execute_staff_action') as execute:
            self.assertIsNone(autonomy.terminal_result(result))
            self.assertTrue(tools.process_staff_request_once())
            self.assertEqual(load(request)['status'],'awaiting_completion')
            doc=load(path);doc.update(status='completed',preparation={'preparationVerified':True},errorType='OldAttemptError',failureReason='old_failure');write(path,doc)
            observed,_=autonomy.terminal_result(result)
            self.assertTrue(observed['preparationVerified'])
            self.assertIsNone(observed['errorType']);self.assertIsNone(observed['reason'])
            self.assertFalse(observed['publicationVerified']);self.assertFalse(observed['reservationVerified'])
            self.assertTrue(tools.process_staff_request_once())
            self.assertEqual(load(request)['status'],'completed')
            self.assertEqual(load(request)['observationHistory'][0]['status'],'unknown')
            execute.assert_not_called()

    def test_observed_yoon_commerce_link_is_bound_and_disclosed_without_opening_other_external_links(self):
        from common import naver_reader as reader,asset_map as assets
        url='https://naver.me/test-issued-link'
        document={'blocks':[{'type':'text','text':'[product details]('+url+')'}]}
        with patch.object(assets,'shopping_link_context',return_value={'products':[{'shortenUrl':url}]}):
            result=reader.normalize_links(document,[],commerce_account='yoon_master')
        self.assertEqual(result['lineLinks'],{'product details':url})
        self.assertIn('수수료',result['blocks'][0]['text'])
        with patch.object(assets,'shopping_link_context',return_value={'products':[]}):
            with self.assertRaisesRegex(ValueError,'external links'):
                reader.normalize_links({'blocks':[{'type':'text','text':'[unknown]('+url+')'}]},[],commerce_account='yoon_master')
        with self.assertRaisesRegex(ValueError,'external links'):
            reader.normalize_links({'blocks':[{'type':'text','text':'[unknown]('+url+')'}]},[],commerce_account='soul5373')


    def test_reconciliation_keeps_exact_native_failure_as_manager_followup(self):
        import hashlib
        row=self.allocation();self.allocate([row])
        args={'action':'naver','date':'2026-11-07','account':'soul5373','slot':'11:00'}
        identity=hashlib.sha256(json.dumps(['parameters',args],sort_keys=True).encode()).hexdigest()
        path=self.data/'publication-conferences'/(identity+'.json')
        write(path,{'kind':'parameters','arguments':args,'status':'failed','failureReason':'editorial_images_held'})
        operating.reconcile_allocations()
        allocation=next(iter(load(operating.STATE)['publications'].values()))
        self.assertEqual(allocation['executionReview']['status'],'failed')
        self.assertEqual(allocation['executionReview']['reason'],'editorial_images_held')
        self.assertFalse(allocation['executionReview']['publicationVerified'])
        self.assertIn(identity,allocation['executionReview']['nativeReceipt'])

    def test_manager_checkpoint_preserves_total_work_and_does_not_finish_the_company(self):
        from agents import crew_reasoning as crew
        row={'id':'c'*64,'origin':'company-manager','status':'ready','decisions':600,'maxSteps':600,
             'permissions':{'repair':False},'actor':'jarvis','timings':{'modelActiveSeconds':7200},'observations':[]}
        with patch.object(crew,'save'),patch.object(crew,'refresh_operating_actions'),patch.object(crew,'refresh_pending',return_value=True),patch.object(crew,'ask') as ask:
            crew._advance(row,1)
        self.assertEqual(row['status'],'waiting');self.assertEqual(row['decisions'],600)
        self.assertEqual(row['timings']['modelActiveSeconds'],7200)
        self.assertEqual(row['cycleCheckpoint']['decisions'],600)
        self.assertNotIn('answer',row);ask.assert_not_called()


if __name__=='__main__':unittest.main()
