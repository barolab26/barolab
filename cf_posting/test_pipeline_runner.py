"""Offline regressions: no models, browser connections, publication or real ledgers."""
import copy
import asyncio
from contextlib import nullcontext
import datetime
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, AsyncMock, patch

import cv2
import numpy as np

from cf_posting import pipeline_runner as p


def rejected_layout():
    return {'status':'rejected', 'issues':['캡션 간격과 이미지 비율 정렬'],
            'checks':{key: key != 'captionPlacement' for key in (*p.BLOG_REQUIRED_CHECKS, 'factsSupported')}}


class PromptTests(unittest.TestCase):
    def test_source_reduction_preserves_primary_identity_and_context_mapping(self):
        inputs={'readerGoal':{'question':'원질문'},'keywords.md':{'title':'확정 제목','topicSlug':'fixed'},
                'observations':{'sources':[{'url':f'https://example.test/{i}','kind':'primary' if i>=3 else 'competitor','excerpt':'근거'} for i in range(6)]},
                'questionContext':[{'id':str(i),'kind':'observed_context','sourceUrl':f'https://example.test/{i}',
                    'sourceTextRef':{'path':f'observations.sources[{i}]','field':'excerpt','charStart':0,'charEnd':2}} for i in range(6)]}
        inputs['questionContext'].append({'id':'request','kind':'explicit_request','text':'원질문'})
        original=copy.deepcopy(inputs); result=p.select_prompt_sources(inputs,4)
        self.assertEqual([x['url'] for x in result['observations']['sources']],
                         [f'https://example.test/{i}' for i in [3,4,5,0]])
        self.assertEqual({x['id'] for x in result['questionContext']},{'3','4','5','0','request'})
        for ctx in result['questionContext'][:-1]:
            index=int(ctx['sourceTextRef']['path'].split('[')[1].split(']')[0])
            self.assertEqual(result['observations']['sources'][index]['url'],ctx['sourceUrl'])
        self.assertEqual(inputs,original)

    def test_search_projection_and_rebudget_keep_references_valid(self):
        source={'url':'https://example.test/kept','excerpt':'근거'*1250,'kind':'primary','content':'긴원문'*4000}
        goal={'question':'변경 금지 질문'}
        inputs={'readerGoal':goal,'keywords.md':{'readerGoal':goal,'title':'고정 제목'},
                'observations':{'sources':[source], 'observedSearches':[
                    {'query':'실제 검색','results':[{'url':source['url'],'title':'선택문서','position':1,'content':'중복'*40000},
                    {'url':'https://example.test/rejected','content':'후보'*40000}]}]},
                'questionContext':[{'id':'one','kind':'observed_context','text':source['excerpt'],'sourceUrl':source['url']},
                                   {'kind':'explicit_request','text':'원질문'*1000}]}
        original=copy.deepcopy(inputs)
        first=p.reference_repeated_context(p.prompt_inputs(inputs))
        second=p.reference_repeated_context(p.prompt_inputs(first,400))
        self.assertEqual(second['keywords.md']['readerGoalRef'],'readerGoal')
        self.assertEqual(len(second['observations']['observedSearches'][0]['results']),1)
        self.assertNotIn('content',second['observations']['observedSearches'][0]['results'][0])
        self.assertEqual(len(second['observations']['sources'][0]['content']),400)
        self.assertEqual(second['questionContext'][0]['sourceTextRef']['charEnd'],400)
        self.assertEqual(second['questionContext'][1]['text'],original['questionContext'][1]['text'])
        self.assertEqual(inputs,original)

    def test_failed_budget_preserves_private_builder_inputs_without_printing_them(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp); folder=base/'output'/'original-slot'/'run'
            with patch.object(p,'BASE_DIR',base),patch.dict(p.RUN_CONTEXT,{'artifactFolder':str(folder),'agent':'researcher'},clear=True):
                with self.assertRaisesRegex(p.ReviewRequired,'prompt_budget_exceeded'):
                    p.agent_prompt('researcher','고정 계약',{'contentHtml':'불변 본문'*20000})
            packet=json.loads((folder/'model-audit/researcher/prompt-budget/builder-input.json').read_text(encoding='utf-8'))
            self.assertEqual(packet['inputs']['contentHtml'],'불변 본문'*20000)
            self.assertGreater(packet['fieldBytes']['contentHtml'],60000)

    def test_production_sized_keyword_history_is_projected_without_losing_selected_sources(self):
        # Mirrors the failed 37KB markdown/28KB JSON packet: selection history was
        # included twice even though the chosen evidence and goal were already present.
        history={'candidates':[{'mainKeyword':'실제 검색 수요 '*100,'observed':'관찰 기록 '*250}]*3}
        keyword={'title':'원래 질문 제목','topicSlug':'original-topic','category':'정보',
                 'readerGoal':{'question':'원래 질문','requiredAnswers':['필요한 답 '*100]*4},
                 'demandEvidence':{'question':'원래 질문','news':[{'url':'https://example.test/evidence','title':'선택 근거 '*100}]},
                 'demandCandidates':history,'selectionRounds':[{'observed':history}],
                 'keywordsMd':'중복 설명 '*500}
        original=copy.deepcopy(keyword)
        sources=[dict(id=f'S{i}',url=f'https://example.test/source-{i}',kind='primary',
                      excerpt=('실제 관찰 근거 자료 '*300)[:2500]) for i in range(6)]
        contexts=p.prepare_question_context([dict(id=f'C{i}',kind='observed_context',
                    text=row['excerpt'],sourceUrl=row['url']) for i,row in enumerate(sources)])
        payload={'keywords.md':keyword,'readerGoal':keyword['readerGoal'],
                 'observations':{'sources':sources},'questionContext':contexts}
        for agent in ('researcher','writer'):
            prompt=p.agent_prompt(agent,'원래 질문과 근거를 보존한다.',payload)
            self.assertLessEqual(p.serialized_prompt_bytes(prompt),60000)
            self.assertNotIn('selectionRounds',prompt);self.assertNotIn('demandCandidates',prompt)
            self.assertIn('https://example.test/evidence',prompt)
            self.assertIn('sourceTextRef',prompt)
            self.assertIn('원래 질문 제목',prompt)
        self.assertEqual(keyword,original)
        compact=p.reference_repeated_context(p.prompt_inputs(payload))
        for row in compact['questionContext']:
            if 'sourceTextRef' in row:
                ref=row['sourceTextRef']; index=int(ref['path'].split('[')[1].split(']')[0])
                original_context=next(ctx for ctx in contexts if ctx['id']==row['id'])
                self.assertEqual(sources[index]['excerpt'][ref['charStart']:ref['charEnd']],original_context['text'])

    def test_recent_catalog_has_15_latest_and_three_fields(self):
        rows = [dict(slug=f'post-{i}', title=f'제목{i}', category='정책', created_at=f'2026-10-{i:02}',
                     excerpt='가' * 50000, id=i) for i in range(1, 30)]
        result = p.prompt_inputs({'publishedCatalog':rows})['publishedCatalog']
        self.assertEqual(len(result), 15)
        self.assertEqual(result[0]['slug'], 'post-29')
        self.assertEqual(result[-1]['slug'], 'post-15')
        self.assertTrue(all(set(row) == {'slug','title','category'} for row in result))
        self.assertIn('excerpt', rows[0])  # Caller inventory is unchanged.

    def test_sources_preserve_six_primary_urls_and_bounded_excerpts(self):
        rows = [dict(id=str(i), kind='competitor' if i < 3 else 'primary', url=f'https://example.test/{i}',
                     text='한글🧠' * 10000) for i in range(12)]
        sources = p.prompt_inputs({'crawledSources':rows})['crawledSources']
        self.assertEqual(len(sources), 6)
        self.assertTrue(all(row['kind'] == 'primary' and len(row['text']) <= 2500 for row in sources))
        self.assertEqual(sources[0]['url'], rows[3]['url'])

    def test_research_and_writer_actual_serialized_utf8_budget(self):
        source = {'id':'S1', 'url':'https://example.test/official', 'kind':'primary',
                  'text':'한글🧠\\"' * 15000, 'quotes':['실제 인용' * 1000] * 6}
        data = {'observations':{'sources':[source] * 12},
                'questionContext':[{'text':'한글🧠' * 15000, 'sourceUrl':source['url']}] * 6,
                'research.md':{'facts':[{'quote':'실제 인용' * 2000, 'sourceUrl':source['url']}] * 6}}
        for agent in ('researcher', 'writer'):
            prompt = p.agent_prompt(agent, 'Preserve the actual task and sources.', data)
            self.assertLessEqual(len(json.dumps(prompt, ensure_ascii=False).encode('utf-8')), 60000)
            self.assertIn(source['url'], prompt)
            self.assertIn('Preserve the actual task', prompt)

    def test_oversized_immutable_contract_blocks_instead_of_truncating(self):
        with self.assertRaisesRegex(p.ReviewRequired, 'prompt_budget_exceeded'):
            p.agent_prompt('writer', 'task', {'answerBrief':{'finalTitle':'가' * 30000}})

    def test_codex_medium_and_final_raw_prompt_guard(self):
        fake_client = SimpleNamespace(generate_json=Mock(return_value={'ok':True}), memory_call=lambda f:f, memory_session=lambda *a:nullcontext())
        fake_settings = SimpleNamespace(load=lambda: {'active':'codex'})
        with patch.dict('sys.modules', {'common.llm_client':fake_client, 'common.llm_settings':fake_settings}), \
             patch.dict(p.RUN_CONTEXT, {'agent':'writer'}, clear=True):
            p.call_model_json('small prompt')
            self.assertEqual(fake_client.generate_json.call_args.kwargs['reasoning_effort'], 'medium')
            with self.assertRaises(p.ReviewRequired):
                p.call_model_json('가' * 30000)
        self.assertEqual(fake_client.generate_json.call_count, 1)


class ReviewTests(unittest.TestCase):
    def test_pre_final_layout_rejection_enters_same_single_repair_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)
            article={'topicSlug':'same-topic','imagePlans':[]}
            (folder/'article.json').write_text(json.dumps(article),encoding='utf-8')
            (folder/'assembled.html').write_text('body',encoding='utf-8')
            (folder/'assembly-edits.json').write_text('[]',encoding='utf-8')
            p.document(folder/'images.md','images',{'imagePlans':[]})
            group=[dict(imageIndex=1,filename='tile.png',viewport='mobile',start=0,end=500,file='tile.png')]
            response={'checks':{'readability':True,'tableFormatting':True,'captionPlacement':False,'visualsServeTask':True},
                      'perImage':[{**group[0],'observedContent':'본문과 사진이 읽히며 캡션 간격 조정 필요',
                                   'alignment':True,'usable':True}], 'issues':['캡션 간격 정렬'], 'notes':[]}
            record={'kind':'layout-mobile','attachments':group,'response':response,
                    'reportFile':'visual-reviews/reviewer/group/response.json'}
            record_path=folder/record['reportFile'];record_path.parent.mkdir(parents=True)
            record_path.write_text(json.dumps(record),encoding='utf-8')
            rows=[{'agent':agent,'outputs':['assembled.html'] if agent=='assembler' else []} for agent in p.Handoff.agents[:5]]
            handoff=SimpleNamespace(folder=folder,file=lambda name:folder/name,data={'stages':rows},check=lambda:rows,save=Mock())
            with patch.object(p,'layout_review_batches',return_value=[group]),patch.object(p,'call_visual_batch',return_value=record):
                with self.assertRaises(p.CosmeticLayoutRequired):
                    p.review_layout_groups(handoff,article,{'coverage':{}},Mock(),Mock(),source_review={'batches':[]})
            self.assertFalse((folder/'review.json').exists())
            self.assertIsNotNone(p.cosmetic_layout_request(folder))
            with patch.object(p,'Handoff',return_value=handoff) as factory,patch.object(p,'require_prewriting_handoff'), \
                 patch.object(p,'validate_article'),patch.object(p,'validate_images'),patch.object(p,'validate_reader_task'),patch.object(p,'preview'):
                factory.agents=tuple(row['agent'] for row in rows)
                p.rework_review_draft(folder,'example.test',[],Mock(),Mock(),Mock())
                with self.assertRaisesRegex(p.ReviewRequired,'repair_exhausted'):
                    p.rework_review_draft(folder,'example.test',[],Mock(),Mock(),Mock())
            self.assertFalse((folder/'review.json').exists())  # No fabricated final approval.
            response['perImage'][0]['usable']=False
            record_path.write_text(json.dumps(record),encoding='utf-8')
            self.assertIsNone(p.cosmetic_layout_request(folder))

    def test_assembly_cosmetic_edit_keeps_raw_verdict_and_requires_final_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)
            for name in ('draft.md','assembled.html','final.html','final.md'):
                (folder/name).write_text('original body',encoding='utf-8')
            handoff=SimpleNamespace(folder=folder, file=lambda name:folder/name, data={'domain':'example.test'}, accept=Mock())
            response={'inputComplete':True,'assemblyReadyForLayoutReview':False,
                      'issues':['캡션 간격 정렬'], 'notes':[], 'edits':[]}
            with patch.object(p,'preview'), patch.object(p,'validate_article'), patch.object(p,'validate_images'), \
                 patch.object(p,'validate_reader_task'):
                p.assemble_with_agent(handoff,{},[],[],lambda *a,**k:copy.deepcopy(response),lambda:{})
                self.assertEqual(p.read_document(folder/'assembly-review.json'),response)
                marker=p.read_document(folder/'surgical-repair-attempted.json')
                self.assertTrue(marker['independentReviewStillRequired'])
                self.assertEqual(marker['count'],1)
                with self.assertRaisesRegex(p.ReviewRequired,'repair_exhausted'):
                    p.assemble_with_agent(handoff,{},[],[],lambda *a,**k:copy.deepcopy(response),lambda:{})
            self.assertEqual(handoff.accept.call_count,1)

    def test_assembly_material_rejection_is_not_relabelled_as_notes(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)
            for name in ('draft.md','assembled.html'):
                (folder/name).write_text('original body',encoding='utf-8')
            handoff=SimpleNamespace(folder=folder, file=lambda name:folder/name, data={}, accept=Mock())
            response={'inputComplete':True,'assemblyReadyForLayoutReview':False,
                      'issues':['필수 실제 이미지 누락'], 'notes':[], 'edits':[]}
            with patch.object(p,'preview'), self.assertRaises(p.ReviewRequired):
                p.assemble_with_agent(handoff,{},[],[],lambda *a,**k:response,lambda:{})
            handoff.accept.assert_not_called()
            self.assertEqual(p.read_document(folder/'assembly-review.json')['issues'],response['issues'])

    def test_final_factual_rejection_is_saved_and_never_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)
            for name in ('article.json','assembled.html','final.html'):
                (folder/name).write_text('{}' if name.endswith('json') else 'body',encoding='utf-8')
            p.document(folder/'images.md','images',{'imagePlans':[]})
            p.document(folder/'layout-evidence.md','layout',{'finalSha256':p.digest(folder/'final.html'),'screenshots':[]})
            handoff=SimpleNamespace(folder=folder,file=lambda name:folder/name,data={},check=Mock(),accept=Mock())
            response={'status':'rejected','issues':['사실 오류'],
                      'checks':{key:key!='factsSupported' for key in (*p.BLOG_REQUIRED_CHECKS,'factsSupported')},'notes':[]}
            with patch.object(p,'validate_reader_task'),patch.object(p,'validate_images'), \
                 patch.object(p,'review_visual_assets',return_value={'batches':[]}), \
                 patch.object(p,'review_layout_groups',return_value=[]), \
                 patch('common.content_improvement.audit_article',return_value={}), \
                 patch.dict(p.RUN_CONTEXT,{},clear=True), self.assertRaises(p.ReviewRequired):
                p.review_article(handoff,{'imagePlans':[]},lambda *a,**k:response,lambda:{})
            handoff.accept.assert_not_called()
            saved=json.loads((folder/'review.json').read_text(encoding='utf-8'))
            self.assertFalse(saved['checks']['factsSupported']);self.assertEqual(saved['status'],'rejected')

    def test_raw_pixel_rejection_and_missing_observation_are_never_forged(self):
        response = {'checks':{'captionsAccurate':False}, 'perImage':[], 'issues':['wrong image'], 'notes':[]}
        record = p.call_visual_batch(None, 'reviewer', 'source', [], 'prompt', [],
                                     lambda *a, **k: response, lambda: {}, {})
        self.assertEqual(record['response'], response)
        self.assertFalse(record['response']['checks']['captionsAccurate'])
        self.assertEqual(record['response']['perImage'], [])

    def test_material_checks_or_mixed_issues_never_enter_cosmetic_repair(self):
        self.assertTrue(p.minor_review_only(rejected_layout()))
        for change in ('factsSupported', 'imagesHonest', 'readerTaskComplete', 'actualCaptureAlignment'):
            report = rejected_layout(); report['checks'][change] = False
            self.assertFalse(p.minor_review_only(report))
        report = rejected_layout(); report['issues'].append('필수 이미지 누락')
        self.assertFalse(p.minor_review_only(report))
        report = rejected_layout(); del report['checks']['factsSupported']
        self.assertFalse(p.minor_review_only(report))

    def test_one_in_place_repair_preserves_rejection_and_source_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            article = {'topicSlug':'same-topic', 'contentHtml':'original body', 'imagePlans':[]}
            (folder/'article.json').write_text(json.dumps(article), encoding='utf-8')
            (folder/'review.json').write_text(json.dumps(rejected_layout()), encoding='utf-8')
            p.document(folder/'images.md', 'images', {'imagePlans':[]})
            (folder/'assembly-edits.json').write_text('[]', encoding='utf-8')
            (folder/'assembled.html').write_text('old formatting', encoding='utf-8')
            report = rejected_layout()
            report.update(articleSha256=p.digest(folder/'article.json'), finalSha256=p.digest(folder/'assembled.html'))
            (folder/'review.json').write_text(json.dumps(report), encoding='utf-8')
            rows = [{'agent':agent, 'outputs':['assembled.html'] if agent == 'assembler' else []}
                    for agent in p.Handoff.agents[:5]]
            handoff = SimpleNamespace(folder=folder, data={'stages':rows}, check=lambda:rows,
                                      file=lambda name:folder/name, save=Mock())
            original = p.digest(folder/'article.json')
            verdict = p.digest(folder/'review.json')
            generate = Mock(side_effect=AssertionError('No new author/image model call'))
            def render(*args, **kwargs):
                (folder/'assembled.html').write_text('normalized formatting', encoding='utf-8')
            with patch.object(p, 'Handoff', return_value=handoff) as factory, \
                 patch.object(p, 'require_prewriting_handoff'), patch.object(p, 'validate_article'), \
                 patch.object(p, 'validate_images'), patch.object(p, 'validate_reader_task'), \
                 patch.object(p, 'preview', side_effect=render):
                factory.agents = tuple(row['agent'] for row in rows)
                p.rework_review_draft(folder, 'example.test', [], generate, Mock(), Mock())
                with self.assertRaisesRegex(p.ReviewRequired, 'repair_exhausted'):
                    p.rework_review_draft(folder, 'example.test', [], generate, Mock(), Mock())
            self.assertEqual(p.digest(folder/'article.json'), original)
            self.assertEqual(p.digest(folder/'review.json'), verdict)
            self.assertEqual(rows[-1]['fileHashes']['assembled.html'], p.digest(folder/'assembled.html'))
            generate.assert_not_called()


class SchedulerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.patch = patch.object(p, 'BASE_DIR', self.base); self.patch.start(); self.addCleanup(self.patch.stop)
        self.now = datetime.datetime(2026,10,19,14,0,tzinfo=p.KST)

    def test_transient_three_attempt_limit_never_resets_history(self):
        item = {'status':'failed','slug':'fixed-topic','title':'원래 제목', 'totalAttempts':67, 'attemptCount':67,
                'lastError':'CDP connect timeout'}
        for attempt in range(1,4):
            item['automaticAttemptCount'] = attempt
            p.schedule_failed_attempt(item, 1, self.now)
            if attempt < 3:
                self.assertEqual(datetime.datetime.fromisoformat(item['nextRetryAt'])-self.now,
                                 datetime.timedelta(minutes=10))
            else:
                self.assertTrue(item['retryExhausted']); self.assertNotIn('nextRetryAt', item)
        self.assertEqual(item['attemptCount'], 67)
        self.assertEqual(item['totalAttempts'], 67)
        self.assertEqual(item['title'], '원래 제목')

    def test_permanent_error_and_publication_receipt_never_retry(self):
        item = {'status':'review_required','slug':'fixed-topic','lastError':'Unsafe article HTML'}
        p.schedule_failed_attempt(item, 1, self.now)
        self.assertFalse(item['retryable']); self.assertNotIn('nextRetryAt', item)
        receipt = self.base/'output'/'fixed-topic'/'publication.json'
        receipt.parent.mkdir(parents=True); receipt.write_text('{"status":"publication_started"}')
        item.update(status='failed', lastError='CDP timeout')
        p.schedule_failed_attempt(item, 1, self.now)
        self.assertEqual(item['status'], 'verification_pending'); self.assertFalse(item['retryable'])

    def test_review_required_schedules_same_artifact_once_after_10min(self):
        folder = self.base/'output'/'fixed-topic'/'run-1'; folder.mkdir(parents=True)
        (folder/'review.json').write_text(json.dumps(rejected_layout()), encoding='utf-8')
        item = {'domain':'smilenote.kr','status':'review_required','slug':'fixed-topic','scheduledTime':'09:00',
                'artifactFolder':'output/fixed-topic/run-1','lastError':'layout review rejected'}
        p.schedule_failed_attempt(item, 1, self.now)
        self.assertEqual(item['reviewReworkFolder'], str(folder))
        sched = {'date':'2026-10-19','items':[item]}
        self.assertEqual(p.select_due_items([sched], self.now), [])
        self.assertEqual(len(p.select_due_items([sched], self.now+datetime.timedelta(minutes=10))), 1)
        (folder/'surgical-repair-attempted.json').write_text('{"count":1}')
        p.schedule_failed_attempt(item, 1, self.now)
        self.assertFalse(item['retryable'])
        self.assertEqual(p.select_due_items([sched], self.now+datetime.timedelta(days=1)), [])

    def test_maintenance_stops_dispatch_without_changing_item(self):
        (self.base/'data').mkdir(); (self.base/'data'/'publisher-maintenance.json').write_text('{"paused":true}')
        item = {'domain':'smilenote.kr','status':'waiting'}; before = copy.deepcopy(item)
        with patch.object(p.subprocess, 'Popen') as process:
            self.assertFalse(p.run_publisher_for_item(item, {'items':[item]}))
        process.assert_not_called(); self.assertEqual(item,before)

    def test_actual_dispatch_caps_repeated_failures_and_keeps_topic(self):
        path = self.base/'schedule.json'
        item = {'id':1,'domain':'smilenote.kr','status':'waiting','slug':'fixed-topic','title':'원래 제목',
                'scheduledTime':'09:00','lastError':'CDP timeout','totalAttempts':67}
        schedule = {'date':'2026-10-19','items':[item]}
        process = Mock(); process.wait.return_value = 1
        with patch.object(p, 'SCHEDULER_LOG_FILE', self.base/'scheduler.log'), \
             patch.object(p, 'save_schedule_file', side_effect=lambda f,d:Path(f).write_text(json.dumps(d),encoding='utf-8')), \
             patch.object(p, 'log_scheduler'), patch.object(p, 'sync_dashboard_status'), \
             patch.object(p, 'load_or_get_schedule', return_value=schedule), \
             patch.object(p.subprocess, 'Popen', return_value=process) as launch:
            for _ in range(4):
                item.pop('nextRetryAt',None)
                p.run_publisher_for_item(item,schedule,path)
                schedule=json.loads(path.read_text(encoding='utf-8')); item=schedule['items'][0]
        self.assertEqual(launch.call_count,3)
        dispatched=json.loads(launch.call_args.kwargs['env']['CF_SLOT_CONTRACT_JSON'])
        self.assertEqual(dispatched,dict(title='원래 제목',topicSlug='fixed-topic',scheduledTime='09:00',domain='smilenote.kr'))
        self.assertEqual(item['totalAttempts'],70)
        self.assertEqual(item['slug'],'fixed-topic'); self.assertEqual(item['title'],'원래 제목')
        self.assertTrue(item['retryExhausted'])


class SlotIdentityTests(unittest.TestCase):
    def setUp(self):
        self.item={'domain':'joynote.kr','title':'원래 분리불안 질문','slug':'original-topic','scheduledTime':'11:10'}
        self.contract=p.scheduled_slot_contract(self.item)

    def test_planner_enum_and_runtime_reject_topic_drift(self):
        seen=[]
        def generate(prompt,response_schema=None):
            seen.append(response_schema)
            return {'candidates':[dict(mainKeyword='카페',question='다른 질문',category='반려동물',title='다른 제목',topicSlug='other-topic')]}
        fixed={'mode':'scheduled_slot','slotContract':self.contract,'explicitReaderQuestion':self.contract['title'],
               'seedTitle':self.contract['title'],'topicSlug':self.contract['topicSlug']}
        with patch.object(p,'_news',return_value=([],None)),self.assertRaisesRegex(p.ReviewRequired,'topic_drift_detected'):
            p.select_keyword_with_demand('instructions',{'domain':'joynote.kr','preferredCategory':'반려동물'},generate,fixed=fixed)
        fields=seen[0]['properties']['candidates']['items']['properties']
        self.assertEqual(fields['title']['enum'],[self.contract['title']])
        self.assertEqual(fields['topicSlug']['enum'],['original-topic'])
        self.assertEqual(fields['question']['enum'],[self.contract['title']])

    def test_researcher_writer_runtime_and_writer_schema_keep_slot(self):
        fake_client=SimpleNamespace(generate_json=Mock(), memory_call=lambda f:f, memory_session=lambda *a:nullcontext())
        fake_settings=SimpleNamespace(load=lambda:{'active':'codex'})
        with patch.dict('sys.modules',{'common.llm_client':fake_client,'common.llm_settings':fake_settings}), \
             patch.dict(p.RUN_CONTEXT,{'agent':'researcher','slotContract':self.contract},clear=True):
            fake_client.generate_json.return_value={'answerBrief':{'finalTitle':'다른 제목'}}
            with self.assertRaisesRegex(p.ReviewRequired,'topic_drift_detected'):p.call_model_json('small')
            p.RUN_CONTEXT.update(agent='writer',approvedTitle=self.contract['title'],approvedTopicSlug='original-topic')
            fake_client.generate_json.return_value={'title':'다른 제목','topicSlug':'other-topic','contentHtml':'body'}
            with self.assertRaisesRegex(p.ReviewRequired,'topic_drift_detected'):p.call_model_json('small')
            schema=fake_client.generate_json.call_args.kwargs['response_schema']
            self.assertEqual(schema['properties']['title']['enum'],[self.contract['title']])
            self.assertEqual(schema['properties']['topicSlug']['enum'],['original-topic'])

    def test_handoff_and_failure_keep_title_slug_and_schedule(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp);folder=base/'output'/'original-topic';folder.mkdir(parents=True)
            keywords={'title':self.item['title'],'topicSlug':self.item['slug'],'mainKeyword':'분리불안','category':'반려동물'}
            p.document(folder/'keywords.md','selected',keywords)
            schedule=base/'schedule.json';schedule.write_text(json.dumps({'items':[self.item]}),encoding='utf-8')
            handoff=SimpleNamespace(folder=folder,check=lambda:[])
            info={'domain':'joynote.kr'}
            with patch.object(p,'BASE_DIR',base),patch.dict(p.RUN_CONTEXT,{'slotContract':self.contract},clear=True), \
                 patch.dict(p.os.environ,{'CF_SCHEDULE_FILE':str(schedule)}),patch.object(p,'update_status'), \
                 patch.object(p,'save_live',side_effect=lambda path,text:Path(path).write_text(text,encoding='utf-8')):
                p.handoff_progress(info,[],'researcher','resume',handoff)
                saved=json.loads(schedule.read_text(encoding='utf-8'))['items'][0]
                self.assertEqual((saved['title'],saved['slug'],saved['scheduledTime']),
                                 (self.item['title'],self.item['slug'],self.item['scheduledTime']))
                bad={**keywords,'title':'카페 제목','topicSlug':'cafe-topic'}
                p.document(folder/'keywords.md','wrong',bad)
                before=schedule.read_bytes()
                with self.assertRaisesRegex(p.ReviewRequired,'topic_drift_detected'):
                    p.handoff_progress(info,[],'researcher','wrong',handoff)
                self.assertEqual(schedule.read_bytes(),before)
            failed=p.failure_blog_info('joynote.kr',{**self.item,'slotContract':self.contract})
            self.assertEqual(failed['title'],self.item['title']);self.assertEqual(failed['topicSlug'],self.item['slug'])

    def test_only_matching_accepted_keyword_stage_resumes_without_planner(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp);folder=base/'output'/'original-topic';folder.mkdir(parents=True)
            keywords={'title':self.item['title'],'topicSlug':'original-topic','category':'반려동물',
                      'mainKeyword':'분리불안','readerGoal':{'question':self.item['title']}}
            p.document(folder/'keywords.md','selected',keywords)
            handoff=SimpleNamespace(folder=folder,check=lambda:[{'agent':'keyword-selector'}])
            scheduled={**self.item,'artifactFolder':'output/original-topic'}
            with patch.object(p,'BASE_DIR',base),patch.object(p,'Handoff',return_value=handoff):
                checkpoint=p.resume_keyword_stage(scheduled,'joynote.kr',self.contract)
                self.assertEqual(checkpoint[0],keywords)
                async def gather(_):raise RuntimeError('reached research without replanning')
                generate=Mock(side_effect=AssertionError('Must not rerun planner'))
                with patch.object(p,'validate_reader_goal'),self.assertRaisesRegex(RuntimeError,'reached research'):
                    asyncio.run(p.draft_agents('joynote.kr','반려동물',['반려동물'],[],generate,gather,Mock(),Mock(),
                        fixed={'slotContract':self.contract,'explicitReaderQuestion':self.item['title']},keyword_checkpoint=checkpoint))
                generate.assert_not_called()
                p.document(folder/'keywords.md','wrong',{**keywords,'topicSlug':'wrong-topic'})
                with self.assertRaisesRegex(p.ReviewRequired,'topic_drift_detected'):
                    p.resume_keyword_stage(scheduled,'joynote.kr',self.contract)
        changed={**self.item,'slotContract':self.contract,'scheduledTime':'12:00'}
        with self.assertRaisesRegex(p.ReviewRequired,'topic_drift_detected'):p.scheduled_slot_contract(changed)

    def test_foreign_checkpoints_rejected_before_any_file_or_stage_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp);folder=base/'output'/'wrong-topic';folder.mkdir(parents=True)
            article={'title':'다른 제목','topicSlug':'wrong-topic','imagePlans':[]}
            (folder/'article.json').write_text(json.dumps(article),encoding='utf-8')
            (folder/'handoff.json').write_text('{"stages":["original"]}',encoding='utf-8')
            before={f.name:f.read_bytes() for f in folder.iterdir()}
            handoff=SimpleNamespace(folder=folder,data={'stages':[]},save=Mock())
            with patch.object(p,'BASE_DIR',base),patch.dict(p.RUN_CONTEXT,{'slotContract':self.contract},clear=True):
                operations=(lambda:p.resume_unpublished_draft({'artifactFolder':'output/wrong-topic'},'joynote.kr',Mock(),Mock(),Mock()),
                            lambda:p.rework_review_draft(folder,'joynote.kr',[],Mock(),Mock(),Mock()),
                            lambda:p.rework_draft(folder,'joynote.kr',[],Mock(),Mock(),Mock()),
                            lambda:p.revalidate_image_handoff(handoff,article,Mock(),Mock(),Mock()))
                for operation in operations:
                    with self.assertRaisesRegex(p.ReviewRequired,'topic_drift_detected'):operation()
                    self.assertEqual({f.name:f.read_bytes() for f in folder.iterdir()},before)
                handoff.save.assert_not_called()

    def test_placeholder_is_unconfirmed_until_real_keyword_acceptance(self):
        placeholder={**self.item,'title':'기획 대기','slug':'live-ai-planning'}
        self.assertIsNone(p.scheduled_slot_contract(placeholder))
        self.assertIsNone(p.scheduled_slot_contract({**placeholder,'slug':'topic-3'}))
        # A deliberately reserved generic title/real slug, including today's smile,
        # is NOT silently treated as a replaceable placeholder.
        generic={**self.item,'title':'핵심 정보 실전 가이드','slug':'smilenote-20261019-essential-guide'}
        self.assertEqual(p.scheduled_slot_contract(generic)['topicSlug'],generic['slug'])
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp);folder=base/'output'/'new-plan';folder.mkdir(parents=True)
            kw={'title':'확정된 새 제목','topicSlug':'new-plan','category':'반려동물',
                'mainKeyword':'분리불안','readerGoal':{'question':'확정된 원래 질문'}}
            p.document(folder/'keywords.md','plan',kw)
            schedule=base/'schedule.json';schedule.write_text(json.dumps({'items':[placeholder]}),encoding='utf-8')
            handoff=SimpleNamespace(folder=folder,check=lambda:[])
            def progress(agent,detail,trace=None):
                if trace:p.handoff_progress({'domain':'joynote.kr'},[],agent,detail,trace)
            async def gather(_):raise RuntimeError('research reached')
            with patch.object(p,'BASE_DIR',base),patch.object(p,'validate_reader_goal'),patch.object(p,'update_status'), \
                 patch.object(p,'save_live',side_effect=lambda path,text:Path(path).write_text(text,encoding='utf-8')), \
                 patch.dict(p.os.environ,{'CF_SCHEDULE_FILE':str(schedule)}), \
                 patch.dict(p.RUN_CONTEXT,{'unplannedSlot':{'scheduledTime':'11:10','domain':'joynote.kr'}},clear=True):
                with self.assertRaisesRegex(RuntimeError,'research reached'):
                    asyncio.run(p.draft_agents('joynote.kr','반려동물',['반려동물'],[],Mock(),gather,progress,Mock(),
                                              keyword_checkpoint=(kw,handoff)))
            saved=json.loads(schedule.read_text(encoding='utf-8'))['items'][0]
            self.assertEqual(saved['slotContract']['title'],kw['title'])
            self.assertEqual(saved['slotContract']['topicSlug'],kw['topicSlug'])
            self.assertEqual(saved['scheduledTime'],'11:10')
            self.assertEqual(saved['readerQuestion'],kw['readerGoal']['question'])


class FinalAdapterBudgetTests(unittest.TestCase):
    def test_only_visible_context_ids_are_allowed_by_schema_and_result(self):
        client=SimpleNamespace(memory_call=lambda f:f,memory_session=lambda *a:nullcontext(),
                               generate_json=Mock(return_value={'answerBrief':{'questionBasis':{'contextId':'removed'}}}))
        schema={'type':'object','properties':{'answerBrief':{'type':'object','properties':{
            'questionBasis':{'type':'object','properties':{'contextId':{'type':'string','enum':['kept','removed']}}}}}}}
        prompt=p.agent_prompt('researcher','보이는 근거만 선택',{'questionContext':[{'id':'kept','kind':'explicit_request','text':'원질문'}]})
        with patch.dict('sys.modules',{'common.llm_client':client}):
            with self.assertRaisesRegex(p.ReviewRequired,'excluded'):
                p.generate_with_prompt_budget(prompt,'codex',response_schema=schema)
        sent=client.generate_json.call_args.kwargs['response_schema']
        self.assertEqual(sent['properties']['answerBrief']['properties']['questionBasis']['properties']['contextId']['enum'],['kept'])
        self.assertEqual(schema['properties']['answerBrief']['properties']['questionBasis']['properties']['contextId']['enum'],['kept','removed'])

    def test_large_real_world_shapes_with_maximum_saved_skill_pair(self):
        import common
        from common import llm_client
        # Real failed run: snapshot 3,752 bytes; largest frozen skill pair 23,657.
        # Retain slightly more than each measured size, with actual decorator.
        memory=SimpleNamespace(frozen_session_context=Mock(return_value='M'*3800),
                               skill_context=Mock(return_value='S'*24000))
        goal={'question':'원래 질문','requiredAnswers':['정확한 요구사항 '*20]*4}
        kw={'title':'고정 예약 제목','topicSlug':'fixed-slot','readerGoal':goal,
            'demandEvidence':{'question':'원래 질문','observed':'확인된 선택 근거 '*160},
            'sourceUrls':[f'https://example.test/{i}' for i in range(12)]}
        sources=[{'url':f'https://example.test/{i}','kind':'primary','excerpt':'공식 실제 근거 '*400} for i in range(6)]
        inputs={'keywords.md':kw,'readerGoal':goal,'observations':{'sources':sources},
                'questionContext':[{'id':str(i),'kind':'observed_context','text':s['excerpt'],'sourceUrl':s['url']} for i,s in enumerate(sources)]}
        for agent in ('researcher','writer'):
            prompt=p.agent_prompt(agent,'원래 제목과 원질문을 보존한다.',inputs)
            with patch.object(common,'hermes_memory',memory,create=True),patch.dict('sys.modules',{'common.hermes_memory':memory}), \
                 patch.object(llm_client,'memory_event'),patch.object(llm_client.settings,'load',return_value={'active':'codex','providers':{'codex':{'model':'fixture'}}}), \
                 patch.object(llm_client,'_enabled_route',return_value=('codex',None)),patch.object(llm_client,'_generate_json',return_value=({'ok':True},'fixture')) as adapter:
                p.generate_with_prompt_budget(prompt,'codex',response_schema={'type':'object'},memory_session_id='offline-max-pair')
            final=p.provider_prompt_prefix('codex',response_schema={'type':'object'})+adapter.call_args.args[0]
            self.assertLessEqual(p.serialized_prompt_bytes(final),60000)
            self.assertIn('M'*3800,final); self.assertIn('S'*24000,final)
            self.assertIn('fixed-slot',final);self.assertIn('https://example.test/5',final)

    def test_real_memory_decorator_injects_once_and_final_provider_text_is_bounded(self):
        import common
        from common import llm_client
        fake_memory=SimpleNamespace(frozen_session_context=Mock(return_value='FROZEN:'+('메모리 '*1100)),
                                    skill_context=Mock(return_value='SKILL:'+('실제 절차 '*900)))
        sources=[{'id':f'S{i}','url':f'https://example.test/{i}','excerpt':'실제 근거 '*600} for i in range(6)]
        prompt=p.agent_prompt('researcher','원질문을 보존한다.',{'observations':{'sources':sources},'readerGoal':{'question':'원질문'}})
        schema={'type':'object'}; images=[Path('실제사진.png')]; observer=Mock()
        for provider in ('codex','openai'):
            fake_memory.frozen_session_context.reset_mock();fake_memory.skill_context.reset_mock()
            config={'active':provider,'providers':{provider:{'model':'fixture'}}}
            with patch.object(common,'hermes_memory',fake_memory,create=True), \
                 patch.dict('sys.modules',{'common.hermes_memory':fake_memory}), \
                 patch.object(llm_client,'memory_event') as event,patch.object(llm_client.settings,'load',return_value=config), \
                 patch.object(llm_client,'_enabled_route',return_value=(provider,None)), \
                 patch.object(llm_client,'_generate_json',return_value=({'ok':True},'fixture')) as adapter:
                self.assertEqual(p.generate_with_prompt_budget(prompt,provider,images=images,response_schema=schema,
                                  observer=observer,memory_session_id='test-frozen-session'),{'ok':True})
            actual=adapter.call_args.args[0]
            final=p.provider_prompt_prefix(provider,images,schema)+actual
            self.assertLessEqual(p.serialized_prompt_bytes(final),60000)
            self.assertEqual(actual.count('FROZEN:'),1);self.assertEqual(actual.count('SKILL:'),1)
            self.assertIn('원질문',actual);self.assertIn('https://example.test/0',actual)
            fake_memory.frozen_session_context.assert_called_once_with('test-frozen-session','common.llm_client')
            fake_memory.skill_context.assert_called_once()
            self.assertEqual(event.call_count,1)
            self.assertEqual(adapter.call_args.args[2],images)
            self.assertEqual(adapter.call_args.args[4],schema)


class FlowPendingTests(unittest.TestCase):
    def test_lost_click_acknowledgement_keeps_write_ahead_hold(self):
        with tempfile.TemporaryDirectory() as tmp:
            images=Path(tmp);plan={'filename':'scene.jpg','prompt':'safe subject','source':'generated'}
            actual=p.enhance_prompt_for_korean_blog(plan['prompt'])
            tile=SimpleNamespace(count=AsyncMock(return_value=1),get_attribute=AsyncMock(return_value='old-image'))
            tile.first=tile
            editor=SimpleNamespace(inner_text=AsyncMock(return_value=actual))
            button=SimpleNamespace(count=AsyncMock(return_value=1),is_enabled=AsyncMock(return_value=True),
                                   bounding_box=AsyncMock(return_value={'x':0,'y':0,'width':100,'height':40}))
            button.first=button
            journal=images/'flow-generation.json'
            async def send(method,params=None):
                if method=='Target.getTargetInfo':return {'targetInfo':{'targetId':'owned-test'}}
                if method=='Browser.getWindowForTarget':return {'windowId':1}
                if method=='Input.dispatchMouseEvent':
                    record=json.loads(journal.read_text(encoding='utf-8'))[0]
                    self.assertEqual(record['status'],'unconfirmed')
                    self.assertIn('submissionAttemptedAt',record)
                    self.assertNotIn('submittedAt',record)
                    raise RuntimeError('Lost click response; outcome unknown')
                return {}
            client=SimpleNamespace(send=send)
            page=SimpleNamespace(bring_to_front=AsyncMock(),context=SimpleNamespace(new_cdp_session=AsyncMock(return_value=client)),
                keyboard=SimpleNamespace(press=AsyncMock()),wait_for_timeout=AsyncMock(),evaluate=AsyncMock(),
                locator=lambda selector:editor if selector=='div.ProseMirror' else button if selector.startswith('button') else tile)
            with self.assertRaisesRegex(RuntimeError,'Lost click'):
                asyncio.run(p._generate_flow_images(page,{'imagePlans':[plan]},[],str(images),progress_callback=Mock()))
            before=journal.read_bytes();page.bring_to_front.reset_mock()
            with self.assertRaisesRegex(p.ReviewRequired,'flow_generation_pending'):
                asyncio.run(p._generate_flow_images(page,{'imagePlans':[plan]},[],str(images)))
            page.bring_to_front.assert_not_called();self.assertEqual(journal.read_bytes(),before)

    def test_unconfirmed_journal_blocks_duplicate_and_downloaded_reuse_preserves_shared_channel(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp); folder=base/'output'/'original'/'run'; images=folder/'images';images.mkdir(parents=True)
            plan={'filename':'scene.jpg','prompt':'Actual subject illustration','source':'generated'}
            journal=images/'flow-generation.json'; record={'filename':'scene.jpg','status':'unconfirmed','promptSha256':'original-proof','submittedAt':'2026-10-19T05:23:25Z'}
            journal.write_text(json.dumps([record]),encoding='utf-8'); original=journal.read_bytes(); page=Mock()
            with self.assertRaisesRegex(p.ReviewRequired,'flow_generation_pending'):
                asyncio.run(p._generate_flow_images(page,{'imagePlans':[plan]},[],str(images)))
            page.assert_not_called(); self.assertEqual(page.mock_calls,[]);self.assertEqual(journal.read_bytes(),original)
            item={'artifactFolder':'output/original/run','lastError':'Flow timed out','automaticAttemptCount':1,'nextRetryAt':'old'}
            with patch.object(p,'BASE_DIR',base):p.schedule_failed_attempt(item,-3)
            self.assertFalse(item['retryable']);self.assertEqual(item['retryReason'],'flow_generation_pending');self.assertNotIn('nextRetryAt',item)
            _,raw=cv2.imencode('.jpg',np.random.default_rng(42).integers(0,255,(256,256,3),dtype=np.uint8))
            target=images/'scene.jpg'; target.write_bytes(raw.tobytes())
            record.update(status='downloaded',promptSha256=p.hashlib.sha256(p.enhance_prompt_for_korean_blog(plan['prompt']).encode()).hexdigest(),sha256=p.digest(target))
            journal.write_text(json.dumps([record]),encoding='utf-8'); completed=journal.read_bytes()
            # Naver calls this same shared generator: a verified existing asset
            # remains usable, with no browser work and no forged new receipt.
            paths=asyncio.run(p._generate_flow_images(page,{'imagePlans':[plan],'category':'naver-account'},[],str(images)))
            self.assertEqual(paths,[str(target)]);self.assertEqual(page.mock_calls,[]);self.assertEqual(journal.read_bytes(),completed)
            changed={**plan,'prompt':'different request'}
            with self.assertRaisesRegex(p.ReviewRequired,'flow_generation_pending'):
                asyncio.run(p._generate_flow_images(page,{'imagePlans':[changed]},[],str(images)))
            self.assertEqual(journal.read_bytes(),completed)


class PublicVerificationTests(unittest.TestCase):
    def test_equivalent_css_passes_but_missing_short_broken_assets_fail(self):
        image='https://www.example.test/media/photo.png'
        body='<p>'+'충분한 본문 설명입니다. '*90+'</p><figure><img src="'+image+'"><figcaption style="color: red;">실제 사진</figcaption></figure>'
        info={'title':'같은 제목','topicSlug':'same-topic','category':'정보','generate_html':lambda urls:body}
        post={'title':info['title'],'slug':info['topicSlug'],'category':info['category'],'status':'published','content':body}
        public='<h1>같은 제목</h1><article>'+body.replace('color: red;','color:red')+'</article>'
        _, raw=cv2.imencode('.png',np.full((100,100,3),128,dtype=np.uint8))
        get=Mock(return_value=SimpleNamespace(status_code=200,content=raw.tobytes()))
        self.assertTrue(p.verify_public_content(post,public,info,[image],image_get=get))
        get.assert_called_once_with(image,timeout=15)
        changed='<h1>같은 제목</h1><article><p>'+'공개 CMS가 정규화한 본문입니다. '*70+'</p><img src="'+image+'"></article>'
        self.assertTrue(p.verify_public_content(post,changed,info,[image,'https://example.test/secondary.png'],image_get=get))
        self.assertFalse(p.verify_public_content(post,public.replace('<h1>같은 제목</h1>',''),info,[image],image_get=get))
        self.assertFalse(p.verify_public_content(post,public.replace(body.replace('color: red;','color:red'),'짧음'),info,[image],image_get=get))
        self.assertFalse(p.verify_public_content(post,public.replace('<img src="'+image+'">',''),info,[image],image_get=get))
        get.return_value=SimpleNamespace(status_code=200,content=b'not an image')
        self.assertFalse(p.verify_public_content(post,public,info,[image],image_get=get))


if __name__ == '__main__':
    unittest.main()
