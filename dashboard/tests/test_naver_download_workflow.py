import json
from io import BytesIO
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from PIL import Image

from common import naver_download_workflow as b


class DownloadWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.folder=Path(self.tmp.name)

    def test_search_parser_reads_arrays_without_executing_code(self):
        html='evil(); items: [{"type":"image","section":"news","title":"photo"}]; items: [call()]'
        self.assertEqual(b.image_items(html),[{'type':'image','section':'news','title':'photo'}])

    def test_slots_preserve_model_queries_and_fill_headings_before_paragraphs(self):
        rows=[{'kind':'text','text':'Introduction.'},{'kind':'image','searchQuery':'actual product photo'},
              {'kind':'heading','text':'First'},{'kind':'text','text':'One.\n\nTwo.'},
              {'kind':'heading','text':'Second'},{'kind':'text','text':'Three.\n\nFour.'}]
        slots=b.ensure_slots(rows,'keyword')
        self.assertEqual(rows[1]['kind'],'image')
        self.assertEqual(sum(x['kind']=='heading' for x in slots),2)
        for i,row in enumerate(slots):
            if row['kind']=='heading':self.assertEqual(slots[i+1]['kind'],'image')
            if row['kind']=='image' and i+1<len(slots):self.assertNotEqual(slots[i+1]['kind'],'image')
        self.assertTrue(all(x['searchQuery']=='actual product photo' for x in slots if x['kind']=='image'))

    def test_pixel_approval_rejects_screenshots_graphics_and_missing_inspection(self):
        row={**{k:True for k in ('inspected','isPhoto','relevant','headingMatch')},
             **{k:False for k in ('chart','table','infographic','logo','advertisement')},
             'confidence':.9,'textAreaRatio':.1}
        self.assertTrue(b.decide(row))
        for key in ('inspected','isPhoto','headingMatch'):
            self.assertFalse(b.decide({**row,key:False}))
        self.assertFalse(b.decide({**row,'chart':True}))
        self.assertFalse(b.decide({**row,'textAreaRatio':.2}))

    def test_reconstruction_uses_original_inert_prompt_and_declares_deviations(self):
        rules,contract,vision=b.source_instructions()
        self.assertIn('첫 문장',rules)
        self.assertIn('searchQuery',contract)
        self.assertIn('UI screenshots',vision)
        evidence=b.protocol_evidence()
        self.assertFalse(evidence['exactOriginalReproduction'])
        self.assertEqual(len(evidence['sourceFiles']),6)

    def test_download_prepare_never_calls_capture_engine_and_missing_photos_are_recorded(self):
        post={'title':'Question','hashtags':['질문'], 'blocks':[
            {'kind':'text','text':'Answer.'},{'kind':'heading','text':'Next step'},
            {'kind':'image','searchQuery':'product photo'}, {'kind':'text','text':'Details.'}]}
        (self.folder/'b-slotted-post.json').write_text(json.dumps(post),encoding='utf-8')
        engine=SimpleNamespace(ACCOUNT_MAP={'account':{'blog_id':'blog'}},
            document_fingerprint=b.digest,validate_document=lambda *args:{'ok':True},
            render_document=lambda *args:'preview')
        with patch('common.source_discovery.research',return_value=[{'url':'https://example.com','text':'source'}]), \
             patch('common.naver_reader.normalize_links'), \
             patch('common.naver_reader.ensure_reader_review') as reader, \
             patch('common.content_quality.ensure_publication_review') as factual, \
             patch('common.flow_images.require_editorial_images',side_effect=AssertionError('B called A capture')), \
             patch.object(b,'choose_photo',return_value=None):
            _,_,doc,plan=b.prepare(engine,'account',self.folder,'question')
            self.assertEqual(plan['workflowProtocol'],b.PROTOCOL)
            self.assertEqual(plan['assets'],[])
            reader.assert_called_once();factual.assert_called_once()
            self.assertEqual(json.loads((self.folder/'b-image-realization.json').read_text())['missing'][0]['slot'],0)
            doc['title']='changed'
            with self.assertRaisesRegex(ValueError,'changed'):b.verify(doc,plan,self.folder,engine)

    def test_download_plan_dispatch_does_not_call_screenshot_verifier(self):
        from common.naver_ab import install_image_slots
        engine=SimpleNamespace(naver_image_sections=lambda d:[],prepare_document_images=lambda *a:None,
            verify_document_images=lambda *a:(_ for _ in ()).throw(AssertionError('A verifier called')))
        install_image_slots(engine)
        with patch.object(b,'verify',return_value={'status':'ready'}) as check:
            self.assertEqual(engine.verify_document_images({}, {'workflowProtocol':b.PROTOCOL}, self.folder),{'status':'ready'})
            check.assert_called_once()

    def test_contact_separator_normalization_preserves_digits_and_other_amounts(self):
        from common.content_improvement import fact_valid
        source={'0':{'status':200,'text':'KODATA | TEL: 1811.6508, 수수료 100원'}}
        fact={'sourceId':'0','quote':source['0']['text'],'claim':'대표번호는 1811-6508입니다.'}
        self.assertTrue(fact_valid(fact,source))
        self.assertFalse(fact_valid({**fact,'claim':'대표번호는 1811-6509입니다.'},source))
        self.assertFalse(fact_valid({**fact,'claim':'대표번호는 1811-6508, 수수료 200원입니다.'},source))

    def test_original_download_failure_uses_fallback_and_binds_actual_image(self):
        data=BytesIO();Image.new('RGB',(400,300),'gray').save(data,format='JPEG')
        candidate={'url':'http://example.com/photo.jpg','fallbackUrl':'https://example.com/photo.jpg',
                   'title':'Actual product','articleUrl':'https://example.com/article','press':'Example'}
        review={**{k:True for k in ('inspected','isPhoto','relevant','headingMatch')},
                **{k:False for k in ('chart','table','infographic','logo','advertisement')},
                'confidence':.9,'textAreaRatio':0,'index':0,'scene':'Product','sourceMark':''}
        with patch.object(b,'photo_candidates',return_value=[candidate]), \
             patch.object(b,'fetch_public',side_effect=[ValueError('HTTP rejected'),(data.getvalue(),candidate['fallbackUrl'])]) as fetch, \
             patch('common.llm_client.generate_json',return_value={'results':[review]}) as model:
            result=b.choose_photo({},'product',self.folder,0,set())
            self.assertEqual(fetch.call_count,2)
            self.assertEqual(result['origin'],'download')
            self.assertTrue(Path(result['originalPath']).is_file())
            self.assertEqual(model.call_args.kwargs['images'],[str(Path(result['originalPath']).with_suffix('.jpg'))])

    def test_cli_uses_the_same_context_module_as_publishing_adapters(self):
        import runpy
        from common import naver_ab
        with patch.object(naver_ab,'main') as canonical:
            runpy.run_module('dashboard.common.naver_ab',run_name='__main__')
            canonical.assert_called_once_with()

    def test_original_research_order_keeps_snippets_separate_from_fetched_evidence(self):
        supplied={'url':'https://example.com/source','text':'provided source','status':200}
        (self.folder/'research.json').write_text(json.dumps({'sources':[supplied]}),encoding='utf-8')
        news=b'<a href="https://n.news.naver.com/article/001/123">Product</a>'
        background='<span class="sds-comps-text">Discovery snippet is not independently verified article evidence.</span>'.encode()
        with patch.object(b,'fetch_public',side_effect=[(news,'https://m.search.naver.com/'),(background,'https://m.search.naver.com/')]), \
             patch('common.source_discovery.public_text',return_value={'url':'https://n.news.naver.com/article/001/123',
                   'status':200,'text':'product usage '*20,'textSha256':'hash'}):
            result=b.research_context('product usage',self.folder,[supplied])
        self.assertTrue(result['noBlogs'])
        self.assertEqual(len(result['articles']),1)
        self.assertEqual(result['backgroundEvidenceStatus'].split(';')[0],'discovery_only')
        evidence=json.loads((self.folder/'research.json').read_text())['sources']
        self.assertEqual(len(evidence),2)
        self.assertFalse(any('Discovery snippet' in r['text'] for r in evidence))

    def test_final_caption_review_receives_actual_photos_and_source_records(self):
        doc={'title':'Question','published':False,'blocks':[]}
        asset={'file':'photo.jpg','sha256':'hash','sourceUrl':'https://example.com/article',
               'downloadEvidence':{'finalUrl':'https://example.com/photo.jpg','title':'Observed caption','review':{'inspected':True}}}
        plan={'assets':[asset]}
        for name,data in [('editor-content.json',doc),('photo-plan.json',plan),('research.json',{'sources':[]})]:
            (self.folder/name).write_text(json.dumps(data),encoding='utf-8')
        engine=SimpleNamespace(ACCOUNT_MAP={'account':{'blog_id':'blog'}},
             validate_document=lambda *args:{'ok':True},render_document=lambda *args:'preview')
        from naver_blog_posting.posting import document_fingerprint
        engine.document_fingerprint=document_fingerprint
        plan['documentSha256']=document_fingerprint(doc)
        (self.folder/'photo-plan.json').write_text(json.dumps(plan),encoding='utf-8')
        def final_review(document,folder,generate):return generate('review',agent_slot='doctor')
        with patch.object(b,'verify'),patch('common.naver_reader.ensure_reader_review'), \
             patch('common.content_quality.ensure_publication_review',side_effect=final_review), \
             patch('common.llm_client.generate_json',return_value={}) as model:
            b.prepare(engine,'account',self.folder,'question')
        self.assertEqual(model.call_args.kwargs['images'],[str(self.folder/'images/photo.jpg')])
        research=json.loads((self.folder/'research.json').read_text())
        self.assertEqual(research['publisherEvidence'][0]['observedSearchCaption'],'Observed caption')

    def test_consultation_times_match_12_and_24_hour_notation_without_accepting_other_times(self):
        from common.content_improvement import fact_valid
        text='전화 상담시간: 평일 9:00~18:00, 전화 1577-2488'
        source={'0':{'status':200,'text':text}}
        fact={'sourceId':'0','quote':text,'claim':'전화 상담시간은 평일 오전 9시부터 오후 6시까지입니다.'}
        self.assertTrue(fact_valid(fact,source))
        self.assertTrue(fact_valid({**fact,'claim':'전화 상담 평일 09:00~18:00'},source))
        self.assertFalse(fact_valid({**fact,'claim':'전화 상담은 오전 6시부터 오후 9시입니다.'},source))
        self.assertFalse(fact_valid({**fact,'claim':'전화 상담시간 09:30~18:00'},source))


if __name__=='__main__':unittest.main()
