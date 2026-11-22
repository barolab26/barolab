"""Fixture integration tests: no browser, provider, publishing or live memory writes.

Live smoke: use build_editorial_assets normally under cf_posting/output, with an
official public source and a real section; no fixture reviewer in the live path.
Inspect status, actual model receipt, source and final PNGs before calling it live.
"""
import copy
from datetime import datetime, timedelta
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image, ImageDraw
from common import editorial_images as e


TEXT = 'Official example: use the capture button to record the screen. No task was executed.'
URL = 'https://www.example.org/help/capture'
SECTION = [{'id': 'procedure', 'heading': 'Capture instructions', 'body': TEXT}]
FIELDS = ('relevant', 'entity_matches', 'event_matches', 'date_matches', 'public_safe',
    'no_private_data', 'not_search_results', 'no_unexecuted_completion', 'credits_preserved',
    'page_attribution_preserved', 'historical_label_correct', 'legible')


def png(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new('RGB', (640, 360), 'white')
    ImageDraw.Draw(image).text((30, 30), TEXT, fill='black')
    image.save(path)


class Browser:
    calls = []
    instances = []
    failure = None
    def __init__(self, directory, name):
        self.space = 123
        self.instances.append(self)
    def call(self, op, timeout, **data):
        self.calls.append((op, data))
        if self.failure:
            raise e.Held(self.failure)
        if data.get('screenshot'):
            png(data['screenshot'])
        return {'ok': True, 'space': 123, 'url': URL, 'title': 'Official capture guide',
            'links': [{'url': URL, 'title': 'Official capture guide'}],
            'text': TEXT, 'text_sha256': e._hash(TEXT.encode()), 'public_only': True,
            'viewport': {'width':640,'height':360},
            'network': [{'url': URL, 'method': 'GET', 'credentials': 'omitted'}],
            'regions': [{'id': 0, 'tag': 'FIGURE', 'text': TEXT, 'credit': 'Official guide',
                'clip': {'x': 0, 'y': 0, 'width': 640, 'height': 360}}]}


def model(stage, payload, images, schema, timeout):
    if stage == 'plan':
        result = {'sections': [{'index': r['index'], 'decision': 'capture', 'query': 'official capture instructions',
            'subject': r['body'][:160], 'event': '', 'date': '', 'reason': 'shows actual instructions'} for r in payload['sections']]}
    elif stage == 'source':
        result = {'index': 0,'reason':'Observed exact public source','focus_quote':''}
    elif stage == 'region':
        result = {'region_id': 0, 'historical': False, 'source_text': TEXT, 'source_date': '',
            'caption': 'Official documentation excerpt; explains capture controls.',
            'alt': 'Capture controls shown in the official documentation', 'reuse_context': 'rights unknown', 'anchor_text': TEXT,
            'attribution_quotes': []}
    else:
        result = {**dict.fromkeys(FIELDS, True), 'reason': 'Exact public documentation region; no executed result.'}
    receipt = {'provider': 'fixture', 'model': 'fixture-vision', 'stage': stage, 'at': e._now(),
        'input_sha256': e._hash(payload), 'image_sha256': [e._png(Path(p)) for p in images],
        'response_sha256': e._hash(result)}
    return result, receipt


class EditorialTests(unittest.TestCase):
    def test_explicit_cf_recovery_keeps_working_space_and_other_tabs(self):
        result = e.build_editorial_assets('Capture guide', SECTION, self.folder,
            sources=[URL], channel='cf', taskspace_id=123)
        self.assertEqual(result['status'], 'ready', result)
        browser = Browser.instances[-1]
        self.assertEqual(browser.workspace_name, 'barolab-cf-flow')
        self.assertEqual(browser.space, 123)

    def test_experiment_can_omit_unavailable_optional_visual_with_durable_reason(self):
        from common.naver_ab import scope
        (self.folder/'workflow-assignment.json').write_text('{"experimentId":"fixture-trial"}')
        sections=[{**SECTION[0],'image_optional':True}]
        def unavailable(stage,payload,images,schema,timeout):
            result,receipt=model(stage,payload,images,schema,timeout)
            if stage=='source':
                result={'index':-1,'reason':'No suitable observed visual','focus_quote':''}
                receipt['response_sha256']=e._hash(result)
            return result,receipt
        with scope({'experimentId':'fixture-trial','arm':'B'},self.folder),patch.object(e,'_model',unavailable):
            result=e.build_editorial_assets('Capture guide',sections,self.folder,sources=[URL],channel='naver')
        self.assertEqual(result['status'],'ready',result)
        self.assertEqual(result['assets'],[])
        self.assertEqual(result['optional_visual_failures'][0]['reason'],'no_suitable_source')
        self.assertFalse(result['optional_visual_failures'][0]['approval'])
        self.assertTrue(e.validate_editorial_assets('Capture guide',sections,self.folder,result,channel='naver'))

    def test_experiment_never_omits_required_visual(self):
        from common.naver_ab import scope
        def unavailable(stage,payload,images,schema,timeout):
            result,receipt=model(stage,payload,images,schema,timeout)
            if stage=='source':
                result={'index':-1,'reason':'No suitable observed visual','focus_quote':''}
                receipt['response_sha256']=e._hash(result)
            return result,receipt
        with scope({'experimentId':'fixture-trial','arm':'B'},self.folder),patch.object(e,'_model',unavailable):
            result=e.build_editorial_assets('Capture guide',SECTION,self.folder,sources=[URL],channel='naver')
        self.assertEqual(result['status'],'held')
        self.assertNotIn('optional_visual_failures',result)

    def test_optional_policy_does_not_turn_budget_or_control_stops_into_ready(self):
        from common.naver_ab import scope
        for reason in ('model_budget_exhausted','user_takeover','unsafe_navigation'):
            with self.subTest(reason=reason),tempfile.TemporaryDirectory() as directory:
                Browser.failure=reason
                with scope({'experimentId':'fixture-trial','arm':'B'},Path(directory)):
                    result=e.build_editorial_assets('Capture guide',[{**SECTION[0],'image_optional':True}],
                                                     Path(directory),sources=[URL],channel='naver')
                self.assertEqual(result['status'],'held')
                self.assertIn(reason,result['reasons'])

    @unittest.skipUnless(shutil.which('node'),'Node required for public-alert scope test')
    def test_public_news_alert_exception_never_matches_other_dialogs_or_redirects(self):
        helper=Path(e.__file__).with_name('editorial_browser.mjs').resolve().as_uri()
        script=r'''
const {knownPublicNewsAlert:allowed}=await import(HELPER);
const url='https://www.hyundaimotorgroup.com/ko/news/genesis-gv90-special-exhibition';
const error='PageDialogOpenedError: a JavaScript alert dialog ("undefined") opened';
console.log(JSON.stringify([allowed(error,url,url),allowed(error,url,url+'/other'),
allowed(error,'https://example.com',url),allowed('JavaScript confirm dialog ("undefined")',url,url),
allowed('PageDialogOpenedError: a JavaScript alert dialog ("login required")',url,url)]));
'''.replace('HELPER',json.dumps(helper))
        result=subprocess.run(['node','--input-type=module','-e',script],capture_output=True,text=True,encoding='utf-8',timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(json.loads(result.stdout),[True,False,False,False,False])

    def test_explicit_source_url_avoids_another_choice_call_but_keeps_visual_reviews(self):
        sections=[{**SECTION[0],'purpose':'Read the original public guide at '+URL}]
        stages=[]
        def choose(stage,payload,images,schema,timeout):
            stages.append(stage)
            if stage=='source':raise AssertionError('Source already exactly specified')
            return model(stage,payload,images,schema,timeout)
        with patch.object(e,'_model',choose):
            result=e.build_editorial_assets('Capture guide',sections,self.folder,sources=[{'url':URL,'text':TEXT}])
        self.assertEqual(result['status'],'ready',result)
        self.assertEqual(stages,['plan','region','review'])
        self.assertTrue(e.validate_editorial_assets('Capture guide',sections,self.folder,result))

    @unittest.skipUnless(shutil.which('node'),'Node required for public-notice scope test')
    def test_only_the_observed_public_suji_notice_can_be_closed(self):
        helper=Path(e.__file__).with_name('editorial_browser.mjs').resolve().as_uri()
        for scenario in ('public','private_form','other_dialog','hidden'):
            script=r'''
const scenario=SCENARIO;let clicks=0;
const button={type:'button',innerText:'닫기',click(){clicks++;}};
const dialog={innerText:scenario==='other_dialog'?'로그인 확인':'운영 안내 수지 전시 안내 주말 주차 안내',
 getBoundingClientRect:()=>({width:scenario==='hidden'?0:520,height:600}),
 querySelector:selector=>selector.startsWith('input')?(scenario==='private_form'?{}:null):button};
globalThis.document={querySelectorAll:()=>[dialog]};
const changed=(await import(HELPER)).dismissSujiOperatingNotice();
console.log(JSON.stringify({changed,clicks}));
'''.replace('SCENARIO',json.dumps(scenario)).replace('HELPER',json.dumps(helper))
            result=subprocess.run(['node','--input-type=module','-e',script],capture_output=True,text=True,encoding='utf-8',timeout=10)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(json.loads(result.stdout),{'changed':scenario=='public','clicks':int(scenario=='public')})

    def test_source_focus_uses_only_a_quote_observed_on_the_actual_page(self):
        for quote,expected in ((TEXT,True),('An invented source sentence that is absent from the observed page.',False)):
            with self.subTest(quote=quote), tempfile.TemporaryDirectory() as directory:
                Browser.calls=[]
                def focused(stage,payload,images,schema,timeout):
                    result,receipt=model(stage,payload,images,schema,timeout)
                    if stage=='source':
                        result['focus_quote']=quote;receipt['response_sha256']=e._hash(result)
                    return result,receipt
                with patch.object(e,'_model',focused):
                    result=e.build_editorial_assets('Capture guide',SECTION,Path(directory),sources=[URL])
                self.assertEqual(result['status'],'ready',result)
                self.assertEqual(any(op=='scroll' for op,_ in Browser.calls),expected)
                if expected:self.assertIn('-focus.png',result['assets'][0]['evidence']['source_screenshot'])
                self.assertTrue(e.validate_editorial_assets('Capture guide',SECTION,Path(directory),result))

    def test_complete_dom_rule_is_not_expanded_to_a_broad_vision_box(self):
        from common import jev
        rule='Every optional examination in this specific service is excluded from private insurance claims.'
        observed={'regions':[{'id':0,'tag':'EXCERPT','text':'Specific service scope\n'+rule,
                             'clip':{'x':20,'y':60,'width':400,'height':150}}]}
        before=copy.deepcopy(observed)
        with patch.object(jev,'inspect_capture_box') as inspect:
            e._refine_regions_with_jev('unused.png',observed,{'subject':'The hospital notice states: '+rule},{})
        inspect.assert_not_called()
        self.assertEqual(observed,before)

    def test_transport_failure_preserves_diagnosis_without_source_retry(self):
        Browser.failure='browser_transport_unavailable'
        result=self.build()
        self.assertEqual(result['reasons'],['browser_transport_unavailable'])
        self.assertEqual(len(Browser.calls),1)
        self.assertFalse(any(op=='finish' for op,_ in Browser.calls))

    def test_real_browser_transport_exception_is_durable_and_never_replayed(self):
        browser=REAL_BROWSER(self.folder,'owned-task')
        with patch('common.ego_taskspace.find_ego_cli',return_value=Path('fixture.exe')), \
             patch('common.ego_taskspace.run_ego_mjs',side_effect=RuntimeError('Failed to connect to ego_cli bootstrap')) as run:
            with self.assertRaisesRegex(e.Held,'browser_transport_unavailable'):
                browser.call('observe',10,url=URL)
        self.assertEqual(run.call_count,1)
        diagnosis=json.loads((self.folder/'browser-01-error.json').read_text(encoding='utf-8'))
        self.assertTrue(diagnosis['effectsUnknown'])
        self.assertIsNone(diagnosis['taskspace'])
        self.assertIn('bootstrap',diagnosis['detail'])

    def test_cf_missing_source_never_generates_a_fallback(self):
        original_name=Browser.__name__
        def choose(stage,payload,images,schema,timeout):
            if stage=='source':
                result={'index':-1,'reason':'No matching public source','focus_quote':''}
                return result,{'at':e._now(),'model':'fixture','response_sha256':e._hash(result),'input_sha256':e._hash(payload)}
            return model(stage,payload,images,schema,timeout)
        try:
            Browser.__name__='_Browser'
            with patch.object(e,'_model',choose),patch.object(e,'_build_flow_asset') as generated:
                result=e.build_editorial_assets('Capture guide',SECTION,self.folder,sources=[URL],channel='cf')
                generated.assert_not_called()
        finally:
            Browser.__name__=original_name
        self.assertEqual(result['status'],'held')
        self.assertIn('no_suitable_source',result['reasons'])

    def test_cf_explicit_optional_sections_can_omit_all_images(self):
        sections=[{**SECTION[0],'image_optional':True}]
        def omit(stage,payload,images,schema,timeout):
            result={'sections':[{'index':0,'decision':'omit','query':'','subject':'','event':'','date':'','reason':'text and table resolve the reader task'}]}
            return result,{'at':e._now(),'model':'fixture','response_sha256':e._hash(result),'input_sha256':e._hash(payload)}
        with patch.object(e,'_model',omit):
            result=e.build_editorial_assets('Capture guide',sections,self.folder,sources=[URL],channel='cf')
        self.assertEqual(result['status'],'ready',result)
        self.assertEqual(result['assets'],[])
        self.assertTrue(e.validate_editorial_assets('Capture guide',sections,self.folder,result,channel='cf'))

    def test_official_google_help_is_not_misclassified_as_search_results(self):
        self.assertFalse(e._is_search('https://support.google.com/accounts/answer/1187538?hl=ko'))
        self.assertFalse(e._is_search('https://support.google.com/calendar/answer/37100'))
        for url in ('https://www.google.com/search?q=backup','https://www.google.co.kr/search?q=backup',
                    'https://www.bing.com/search?q=backup','https://search.naver.com/search.naver?query=backup'):
            self.assertTrue(e._is_search(url),url)
        with self.assertRaises(e.Held):e._public_url('https://accounts.google.com/signin/recovery')

    def test_naver_budget_hold_cannot_become_ready_by_omitting_a_later_optional_capture(self):
        from common import jev
        (self.folder/'planning.json').write_text(json.dumps({'identity':'soultin'}),encoding='utf-8')
        sections=[{**SECTION[0],'id':'first'},
                  {**SECTION[0],'id':'second','image_optional':True}]
        original_name=Browser.__name__
        try:
            Browser.__name__='_Browser'
            with patch.object(e,'MAX_MODEL_CALLS',4), \
                 patch.object(jev,'inspect_published_visual',return_value={'status':'ok','passed':True}):
                result=e.build_editorial_assets('Capture guide',sections,self.folder,sources=[URL],channel='naver')
        finally:
            Browser.__name__=original_name
        self.assertEqual(result['status'],'held',result)
        self.assertIn('model_budget_exhausted',result['reasons'])
        self.assertFalse(result['assets'])
        self.assertEqual(len(result['partial_assets']),1)

    def test_naver_can_require_five_images_without_a_four_image_quota(self):
        sections=[{**SECTION[0],'id':'step-'+str(i)} for i in range(5)]
        result=e.build_editorial_assets('Capture guide',sections,self.folder,sources=[URL],channel='naver')
        self.assertEqual(result['status'],'ready',result)
        self.assertEqual(len(result['assets']),5)
        self.assertTrue(e.validate_editorial_assets('Capture guide',sections,self.folder,result,channel='naver'))

    def test_text_complete_naver_article_can_have_no_images_with_bound_omissions(self):
        sections=[{**SECTION[0],'image_optional':True}]
        def omit(stage,payload,images,schema,timeout):
            result={'sections':[{'index':0,'decision':'omit','query':'','subject':'','event':'','date':'',
                                'reason':'Text already gives the complete reader action.'}]}
            return result,{'provider':'fixture','model':'fixture','stage':stage,'at':e._now(),
                'input_sha256':e._hash(payload),'image_sha256':[],'response_sha256':e._hash(result)}
        with patch.object(e,'_model',omit):
            result=e.build_editorial_assets('Capture guide',sections,self.folder,channel='naver')
        self.assertEqual(result['status'],'ready',result)
        self.assertFalse(Browser.calls)
        self.assertTrue(e.validate_editorial_assets('Capture guide',sections,self.folder,result,channel='naver'))
        result['plan']['sections'][0]['reason']=''
        result.pop('manifest_sha256');result['manifest_sha256']=e._hash(result)
        (self.folder/e.MANIFEST).write_text(e._json(result),encoding='utf-8')
        self.assertFalse(e.validate_editorial_assets('Capture guide',sections,self.folder,result,channel='naver'))

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        Browser.calls = []
        Browser.failure = None
        for name, replacement in (('_Browser', Browser), ('_model', model)):
            p = patch.object(e, name, replacement)
            p.start()
            self.addCleanup(p.stop)
        p = patch.object(e.socket, 'getaddrinfo', return_value=[(2, 1, 6, '', ('93.184.215.14', 443))])
        p.start()
        self.addCleanup(p.stop)

    def build(self, sections=SECTION):
        return e.build_editorial_assets('Capture guide', sections, self.folder, sources=[URL])

    def test_source_selection_sees_evidence_after_long_navigation_prefix(self):
        seen=[]
        def inspect_source(stage,payload,images,schema,timeout):
            if stage=='source':
                seen.append(payload['candidates'][0]['text'])
            return model(stage,payload,images,schema,timeout)
        with patch.object(e,'_model',inspect_source):
            result=e.build_editorial_assets('Capture guide',SECTION,self.folder,
                sources=[{'url':URL,'text':'navigation '*500+TEXT}])
        self.assertEqual(result['status'],'ready',result)
        self.assertIn(TEXT,seen[0])

    def valid(self, result, sections=SECTION):
        return e.validate_editorial_assets('Capture guide', sections, self.folder, result)

    def test_search_source_capture_independent_review_and_reuse(self):
        result = self.build()
        self.assertEqual(result['status'], 'ready', result)
        self.assertTrue(self.valid(result))
        self.assertEqual([r[0] for r in Browser.calls], ['observe', 'observe', 'finish'])
        self.assertIn('google.com/search', Browser.calls[0][1]['url'])
        self.assertEqual(Browser.calls[1][1]['url'], URL)
        self.assertEqual(Path(result['assets'][0]['path']).parent, self.folder/'images')
        self.assertEqual(result['assets'][0]['origin'], 'screenshot')
        self.assertEqual(result['assets'][0]['evidence']['review_receipt']['image_sha256'],
                         [result['assets'][0]['sha256'],result['assets'][0]['evidence']['source_screenshot_sha256']])
        before = len(Browser.calls)
        self.assertEqual(self.build(), result)
        self.assertEqual(len(Browser.calls), before)

    def test_changed_article_section_image_source_manifest_rejected(self):
        result = self.build()
        self.assertFalse(e.validate_editorial_assets('Different title', SECTION, self.folder, result))
        changed = copy.deepcopy(SECTION)
        changed[0]['body'] += ' Added claim.'
        self.assertFalse(self.valid(result, changed))
        tampered = copy.deepcopy(result)
        tampered['assets'][0]['sourceUrl'] = 'https://wrong.example.org/'
        self.assertFalse(self.valid(tampered))
        Path(result['assets'][0]['path']).write_bytes(b'changed')
        self.assertFalse(self.valid(result))

    def test_research_excerpt_guides_selection_but_cannot_approve_capture(self):
        observed = {}
        def inspect(stage, payload, images, schema, timeout):
            if stage == 'source':
                observed.update(payload['candidates'][0])
            result, receipt = model(stage, payload, images, schema, timeout)
            if stage == 'review':
                result['entity_matches'] = False
                receipt['response_sha256'] = e._hash(result)
            return result, receipt
        with patch.object(e, '_model', inspect):
            result = e.build_editorial_assets('Capture guide', SECTION, self.folder,
                sources=[{'url': URL, 'title': 'Guide', 'excerpt': 'Observed FAQ answer', 'text': 'Old overview'}])
        self.assertEqual(observed['text'], 'Observed FAQ answer')
        self.assertEqual(result['status'], 'held')
        self.assertTrue(any(op == 'observe' and data.get('url') == URL for op, data in Browser.calls))
        self.assertFalse(self.valid(result))

    def test_manifest_mutation_is_rejected(self):
        result = self.build()
        result['assets'][0]['caption'] = 'Wrong event'
        (self.folder/e.MANIFEST).write_text(json.dumps(result), encoding='utf-8')
        self.assertFalse(self.valid(result))

    def test_naver_cannot_promote_a_generated_asset_to_verified_source_capture(self):
        result=e.build_editorial_assets('Capture guide',SECTION,self.folder,sources=[URL],channel='naver')
        self.assertEqual(result['status'],'ready')
        asset=result['assets'][0]
        asset['origin']='flow_illustration'
        asset['evidence']['flowGenerated']=True
        result.pop('manifest_sha256')
        result['manifest_sha256']=e._hash(result)
        (self.folder/e.MANIFEST).write_text(e._json(result),encoding='utf-8')
        self.assertFalse(e.validate_editorial_assets('Capture guide',SECTION,self.folder,result,channel='naver'))

    def test_rehashed_manifest_cannot_relabel_reviewed_source(self):
        result = self.build()
        asset = result['assets'][0]
        asset['sourceUrl'] = asset['evidence']['url'] = 'https://wrong.example.org/news'
        result.pop('manifest_sha256')
        result['manifest_sha256'] = e._hash(result)
        (self.folder/e.MANIFEST).write_text(json.dumps(result), encoding='utf-8')
        self.assertFalse(self.valid(result))

    def test_original_capture_mutation_is_rejected(self):
        result = self.build()
        p = self.folder / result['assets'][0]['evidence']['source_screenshot']
        p.write_bytes(b'changed')
        self.assertFalse(self.valid(result))

    def test_pixel_crop_is_exact_and_requires_original_hash_and_scale(self):
        source, output = self.folder/'source.png', self.folder/'crop.png'
        png(source)
        original_hash = e._png(source)
        region = {'clip':{'x':10.5,'y':20.5,'width':200,'height':100}}
        receipt = e._crop_snapshot(source,output,region,{'width':640,'height':360},original_hash)
        self.assertEqual(receipt['box'],[10,20,211,121])
        self.assertEqual(e._png(source),original_hash)
        with Image.open(source) as original, Image.open(output) as cropped:
            self.assertEqual(original.crop((10,20,211,121)).tobytes(),cropped.tobytes())
        with self.assertRaisesRegex(e.Held,'scale_unknown'):
            e._crop_snapshot(source,output,region,{'width':1280,'height':720},original_hash)
        with self.assertRaisesRegex(e.Held,'source_screenshot_changed'):
            e._crop_snapshot(source,output,region,{'width':640,'height':360},'0'*64)

    def test_expired_or_future_approval_fails_without_changing_hashes(self):
        result = self.build()
        self.assertTrue(self.valid(result))
        for days in (-2, 2):
            class ShiftedClock(datetime):
                @classmethod
                def now(cls, tz=None):
                    return datetime.now(tz) + timedelta(days=days)
            with patch.object(e, 'datetime', ShiftedClock):
                self.assertFalse(self.valid(result))

    def test_user_takeover_holds_without_finish_or_retry(self):
        Browser.failure = 'user_takeover'
        result = self.build()
        self.assertEqual(result['status'], 'held')
        self.assertEqual(result['assets'], [])
        self.assertEqual(result['reasons'], ['user_takeover'])
        self.assertEqual(len(Browser.calls), 1)
        self.assertFalse(self.valid(result))
        self.assertEqual(self.build()['reasons'], ['existing_manifest_requires_review'])
        self.assertEqual(len(Browser.calls), 1)

    def test_failed_acquisition_requires_same_explicit_space_and_preserves_protected_holds(self):
        Browser.failure='browser_held'
        failed=self.build();self.assertEqual(failed['taskspace_id'],123)
        calls=len(Browser.calls)
        self.assertEqual(e.build_editorial_assets('Capture guide',SECTION,self.folder,sources=[URL],taskspace_id=999)['reasons'],['existing_manifest_requires_review'])
        self.assertEqual(len(Browser.calls),calls)
        Browser.failure=None
        resumed=e.build_editorial_assets('Capture guide',SECTION,self.folder,sources=[URL],taskspace_id=123)
        self.assertEqual(resumed['status'],'ready',resumed)

    def test_explicit_resume_reuses_bound_partial_approval_and_keeps_call_budget(self):
        sections=[{**SECTION[0],'id':'one'},{**SECTION[0],'id':'two'}]
        def fail_second(stage,payload,images,schema,timeout):
            if stage=='source' and payload['section']['index']==1:raise e.Held('no_suitable_region')
            return model(stage,payload,images,schema,timeout)
        with patch.object(e,'_model',fail_second):
            failed=self.build(sections)
        self.assertEqual(len(failed['partial_assets']),1)
        self.assertFalse(e.validate_editorial_assets('Capture guide',sections,self.folder,failed))
        calls=[]
        def observe_model(stage,payload,images,schema,timeout):
            calls.append((stage,payload.get('section',{}).get('index')))
            return model(stage,payload,images,schema,timeout)
        with patch.object(e,'_model',observe_model):
            ready=e.build_editorial_assets('Capture guide',sections,self.folder,sources=[URL],taskspace_id=123)
        self.assertEqual(ready['status'],'ready',ready)
        self.assertEqual(ready['reused_section_indices'],[0])
        self.assertEqual(calls,[('source',1),('region',1),('review',1)])
        self.assertEqual(ready['budget']['model_calls'],failed['budget']['model_calls']+3)
        self.assertTrue(e.validate_editorial_assets('Capture guide',sections,self.folder,ready))

    def test_negative_visual_evidence_holds(self):
        def reject(*args):
            result, receipt = model(*args)
            if args[0] == 'review':
                result['entity_matches'] = False
            return result, receipt
        with patch.object(e, '_model', reject):
            result = self.build()
        self.assertEqual(result['reasons'], ['visual_review_rejected'])
        self.assertEqual(result['assets'], [])
        self.assertNotIn('finish', [r[0] for r in Browser.calls])

    def test_visual_receipt_must_bind_actual_image_bytes(self):
        def wrong(*args):
            result, receipt = model(*args)
            if args[0] == 'review':
                receipt['image_sha256'] = ['0'*64]
            return result, receipt
        with patch.object(e, '_model', wrong):
            result = self.build()
        self.assertEqual(result['reasons'], ['visual_receipt_not_bound_to_image'])

    def test_doctor_uses_configured_vision_route_without_settings_mutation(self):
        shot = self.folder/'fixture.png'
        png(shot)
        def generate(prompt, **kw):
            self.assertEqual(kw['agent_slot'],'doctor')
            self.assertEqual(kw['provider'],'codex')
            self.assertEqual(kw['images'],[str(shot)])
            self.assertFalse(kw['allow_provider_recovery'])
            kw['observer']('codex','configured-vision','returned',actual_model='configured-vision')
            return {'approved':True}
        brains = lambda slot: {'provider':'agy','model':'configured-text'} if slot=='doctor' else {'provider':'codex','model':'configured-vision'}
        with patch('common.llm_settings.get_agent_brain',side_effect=brains), patch('common.llm_client.generate_json',side_effect=generate) as call:
            _, receipt = REAL_MODEL('review',{'evidence':'fixture'},[str(shot)],e._schema({'approved':{'type':'boolean'}}),10)
            self.assertEqual(call.call_count,1)
            self.assertEqual(receipt['requested_slot'],'doctor')
            self.assertEqual(receipt['provider'],'codex')
            self.assertEqual(receipt['image_sha256'],[e._png(shot)])
            self.assertEqual(receipt['routing_reason'],'configured_publi_vision_for_independent_review')

    def test_no_configured_vision_route_holds_before_model_call(self):
        with patch('common.llm_settings.get_agent_brain',return_value={'provider':'agy','model':'text'}), patch('common.llm_client.generate_json') as call:
            with self.assertRaisesRegex(e.Held,'no_verified_vision_transport'):
                REAL_MODEL('review',{},['unused.png'],{},10)
            call.assert_not_called()

    def test_real_adapter_preserves_negative_review_and_source_rejection(self):
        shot = self.folder/'fixture.png'
        png(shot)
        rejected = {**dict.fromkeys(FIELDS, True), 'entity_matches': False,
                    'credits_preserved': False, 'page_attribution_preserved': False,
                    'legible': False, 'reason': 'Relevant but not official; credit is missing.'}
        def generate(prompt, **kw):
            kw['observer']('codex', 'configured-vision', 'returned', actual_model='configured-vision')
            return copy.deepcopy(rejected if kw.get('images') else {'index': -1})
        with patch('common.llm_settings.get_agent_brain', return_value={'provider':'codex','model':'configured-vision'}), patch('common.llm_client.generate_json',side_effect=generate):
            review, _ = REAL_MODEL('review', {'intention': {'event':'','date':''},
                'evidence': {'text': TEXT*3}}, [str(shot)], e._schema({}), 10)
            self.assertEqual(review, rejected)
            choice, _ = REAL_MODEL('source', {'candidates':[{'url':URL}]}, [], e._schema({}), 10)
            self.assertEqual(choice['index'], -1)

    def test_real_adapter_preserves_observed_attribution_and_exact_anchor(self):
        selected = {'region_id': -1, 'attribution_quotes': ['Copyright observed author'],
                    'source_text': 'not observed', 'anchor_text': 'wrong anchor'}
        def generate(prompt, **kw):
            kw['observer']('codex','configured-vision','returned',actual_model='configured-vision')
            return copy.deepcopy(selected)
        with patch('common.llm_settings.get_agent_brain', return_value={'provider':'codex','model':'configured-vision'}), patch('common.llm_client.generate_json',side_effect=generate):
            result, _ = REAL_MODEL('region', {'evidence': {'text':TEXT}, 'section':{'body':TEXT}}, [], e._schema({}), 10)
            self.assertEqual(result, selected)

    def test_injection_code_is_never_executed(self):
        def malicious(*args):
            result, receipt = model(*args)
            if args[0] == 'source':
                result = {'index': '__import__("os").system("anything")','reason':'Untrusted injected source choice','focus_quote':''}
            return result, receipt
        with patch.object(e, '_model', malicious):
            result = self.build()
        self.assertEqual(result['reasons'], ['no_suitable_source'])

    def test_private_redirect_or_search_result_cannot_be_asset(self):
        original = Browser.call
        for bad in ('http://127.0.0.1/secret', 'https://www.google.com/search?q=x'):
            with self.subTest(bad=bad), tempfile.TemporaryDirectory() as directory:
                def redirected(browser, op, timeout, **kw):
                    value = original(browser, op, timeout, **kw)
                    if kw.get('screenshot'):
                        value['url'] = bad
                    return value
                with patch.object(Browser, 'call', redirected):
                    result = e.build_editorial_assets('Capture guide', SECTION, directory)
                self.assertEqual(result['status'], 'held')
                self.assertEqual(result['assets'], [])

    def test_source_quote_cannot_be_invented(self):
        def wrong(*args):
            result, receipt = model(*args)
            if args[0] == 'region':
                result['source_text'] = 'Invented unsupported source text.'
            return result, receipt
        with patch.object(e, '_model', wrong):
            self.assertEqual(self.build()['reasons'], ['source_quote_not_observed'])

    def test_short_observed_author_is_preserved_without_substring_attribution(self):
        pick={'caption':'Actual recipe photo','attribution_quotes':['Lee']}
        caption, credit=e._attributed_caption(pick, {'title':'Recipe','url':URL,'text':'Author: Lee. Actual recipe.'})
        self.assertIn('Lee',caption)
        self.assertIn('Lee',credit)
        with self.assertRaisesRegex(e.Held,'attribution_not_observed'):
            e._attributed_caption(pick, {'title':'Recipe','url':URL,'text':'Author: LeeAnn.'})

    def test_pixel_only_attribution_requires_an_independent_bound_transcription(self):
        quote='Copyright 2026 Example Publisher.'
        pick={'caption':'Actual source view','attribution_quotes':[quote]}
        ev={'url':URL,'title':'Official guide','text':TEXT,'source_screenshot_sha256':'source-image-hash'}
        with self.assertRaisesRegex(e.Held,'attribution_not_observed'):
            e._attributed_caption(pick,ev)
        payload={'source_url':URL,'source_screenshot_sha256':'source-image-hash'}
        ev['visual_attribution']={'quotes':[quote],'receipt':{'stage':'attribution','at':e._now(),
            'input_sha256':e._hash(payload),'image_sha256':['source-image-hash'],
            'response_sha256':e._hash({'quotes':[quote]})}}
        self.assertIn(quote,e._attributed_caption(pick,ev)[0])
        ev['visual_attribution']['receipt']['image_sha256']=['different-image']
        with self.assertRaisesRegex(e.Held,'attribution_not_observed'):
            e._attributed_caption(pick,ev)

    def test_account_keeper_never_claims_or_closes_live_capture_spaces(self):
        from common import ego_taskspace
        with patch.object(ego_taskspace,'_ensure_ego_window_visible_on_desktop',return_value={'mode':'sandbox_desktop'}), patch.object(ego_taskspace,'run_ego_mjs',return_value={}) as call:
            ego_taskspace.ensure_persistent_ego_spaces()
        script=call.call_args.args[0]
        harness="""
const touched=[];
const names=['barolab-soultin','barolab-soul5373','barolab-yoon_master','barolab-kin-adinfo0905','barolab-kin-stone0747','barolab-cf-flow'];
globalThis.listTaskSpaces=async()=>[...names.map((name,id)=>({name,id,recentTabTitles:id===0?['Existing page','Live SmartEditor']:['Existing page']})),
 {id:100,name:'editorial-live-agent',ownership:'agent'},
 {id:101,name:'editorial-live-user',ownership:'user'}];
globalThis.profiles=async()=>[];
globalThis.taskSpace=globalThis.claimTaskSpace=globalThis.takeOverTaskSpace=async id=>{
 touched.push(id);return {finish:async()=>touched.push('finished')};};
"""+script+"\nconsole.log('TOUCHES:'+JSON.stringify(touched));"
        result=subprocess.run(['node','--input-type=module','-e',harness],capture_output=True,text=True,check=True)
        self.assertIn('TOUCHES:[]',result.stdout)

    def test_observed_page_attribution_is_rendered_or_review_holds(self):
        credit = 'Copyright Example contributors. Content available under a Creative Commons license.'
        original = Browser.call
        def attributed_source(browser, *args, **kw):
            value = original(browser, *args, **kw)
            value['text'] += '\n' + credit
            return value
        for preserve in (True, False):
            def review_caption(*args):
                result, receipt = model(*args)
                if args[0] == 'region':
                    result['attribution_quotes'] = [credit] if preserve else []
                elif args[0] == 'review':
                    self.assertEqual(len(args[2]),2)  # final crop and original viewport
                    result['page_attribution_preserved'] = credit in args[1]['rendered_caption']
                    result['credits_preserved'] = True  # page footer is not an in-image mark
                receipt['response_sha256'] = e._hash(result)
                return result, receipt
            with tempfile.TemporaryDirectory() as directory, patch.object(Browser,'call',attributed_source), patch.object(e,'_model',review_caption):
                result = e.build_editorial_assets('Capture guide',SECTION,directory)
                self.assertEqual(result['status'],'ready' if preserve else 'held',result)
                if preserve:
                    self.assertIn(credit,result['assets'][0]['caption'])
                    self.assertIn(URL,result['assets'][0]['source_credit'])
                    self.assertTrue(e.validate_editorial_assets('Capture guide',SECTION,directory,result))
                    result['assets'][0]['caption'] = 'Attribution removed'
                    self.assertFalse(e.validate_editorial_assets('Capture guide',SECTION,directory,result))
                else:
                    self.assertEqual(result['reasons'],['visual_review_rejected'])

    def test_unobserved_license_cannot_be_added_to_caption(self):
        def invented(*args):
            result, receipt = model(*args)
            if args[0]=='region':
                result['attribution_quotes']=['Unrestricted commercial reuse is permitted.']
            return result, receipt
        with patch.object(e,'_model',invented):
            self.assertEqual(self.build()['reasons'],['attribution_not_observed'])

    def test_text_attribution_never_excuses_erased_in_image_credit(self):
        def erased(*args):
            result, receipt = model(*args)
            if args[0]=='review':
                result['credits_preserved']=False
                result['page_attribution_preserved']=True
            return result, receipt
        with patch.object(e,'_model',erased):
            self.assertEqual(self.build()['reasons'],['visual_review_rejected'])

    def test_historical_image_requires_label(self):
        def wrong(*args):
            result, receipt = model(*args)
            if args[0] == 'region':
                result['historical'] = True
            return result, receipt
        with patch.object(e, '_model', wrong):
            self.assertEqual(self.build()['reasons'], ['archive_not_labelled'])

    def test_explicit_optional_only_can_be_omitted(self):
        def omitted(*args):
            result, receipt = model(*args)
            if args[0] == 'plan':
                result['sections'][0]['decision'] = 'omit'
                receipt['response_sha256'] = e._hash(result)
            return result, receipt
        with patch.object(e, '_model', omitted):
            required = self.build()
            self.assertEqual(required['reasons'], ['required_image_omitted'])
            with tempfile.TemporaryDirectory() as directory:
                optional = [{**SECTION[0], 'image_optional': True}]
                value = e.build_editorial_assets('Capture guide', optional, directory)
                self.assertEqual(value['status'], 'ready', value)
                self.assertEqual(value['assets'], [])
                self.assertTrue(e.validate_editorial_assets('Capture guide', optional, directory, value))
        self.assertEqual(Browser.calls, [])

    def test_budget_and_model_failures_hold(self):
        with patch.object(e, 'MAX_MODEL_CALLS', 1):
            self.assertEqual(self.build()['reasons'], ['model_budget_exhausted'])

    def test_more_than_four_required_sections_hold_before_browser(self):
        sections = [{**SECTION[0], 'id': str(i)} for i in range(5)]
        self.assertEqual(self.build(sections)['reasons'], ['image_budget_exhausted'])
        self.assertEqual(Browser.calls, [])

    def test_model_can_inspect_next_viewport_in_same_space(self):
        turns = []
        def scrolling(*args):
            result, receipt = model(*args)
            if args[0] == 'region':
                turns.append(1)
                if len(turns) == 1:
                    result['region_id'] = -2
                    receipt['response_sha256'] = e._hash(result)
            return result, receipt
        with patch.object(e, '_model', scrolling):
            result = self.build()
        self.assertEqual(result['status'], 'ready', result)
        self.assertTrue(self.valid(result))
        self.assertEqual([r[0] for r in Browser.calls], ['observe', 'observe', 'scroll', 'finish'])
        self.assertEqual(result['taskspace_id'], 123)

    def test_browser_parser_accepts_installed_cli_stderr_channel(self):
        # Exercise the actual transport/parser with a fake subprocess only.
        # setUp replaces the class; read the class through the original module
        # test seam saved below to avoid ever invoking the real browser.
        with patch('common.ego_taskspace.find_ego_cli', return_value=Path('ego.exe')), patch.object(e.subprocess, 'run') as run:
            run.return_value.returncode = 0
            run.return_value.stdout = ''
            run.return_value.stderr = 'EDITORIAL_JSON:{"ok":true,"space":314}\n'
            browser = REAL_BROWSER(self.folder, 'test')
            self.assertEqual(browser.call('observe', 5, url=URL)['space'], 314)
            self.assertEqual(browser.space, 314)

    def test_filename_traversal_and_private_addresses(self):
        for path in ('../escape.png', str(self.folder.parent/'outside.png')):
            with self.assertRaises(e.Held):
                e._path(self.folder, path)
        for url in ('file:///a', 'http://127.0.0.1/a', 'http://[::1]/', 'https://user:secret@example.org/',
                    'https://example.org/payment', 'https://example.org/?token=secret', 'http://169.254.169.254/'):
            with self.subTest(url=url), self.assertRaises(e.Held):
                e._public_url(url)

    def observe_dom_fixture(self, fixture):
        """Run the real page.evaluate callbacks against a layout/DOM fixture.

        Only the EGO transport and DOM geometry/styles are fixtures: observe is
        neither copied nor replaced, and no browser, DNS or network is invoked.
        """
        helper = Path(e.__file__).with_name('editorial_browser.mjs').resolve().as_uri()
        request = self.folder/'observe-fixture.json'
        request.write_text(e._json({'op':'inspect','space':314,'url':'https://8.8.8.8/source'}),encoding='utf-8')
        harness = r'''
const fixture=FIXTURE;
Object.assign(globalThis,{innerWidth:640,innerHeight:360,scrollX:0,scrollY:0,
  location:{href:'https://8.8.8.8/source'}});
function element(data) {
  const e={tagName:data.tag||'H2',role:data.role,children:[],innerText:data.text??'Visible source heading',
    closest(selector){
      for(let node=this;node;node=node.parentElement) {
        if(selector==='nav,[role=navigation]' && (node.tagName==='NAV'||node.role==='navigation'))return node;
        if(selector==='figure' && node.tagName==='FIGURE')return node;
      }
      return null;
    },style:{display:'block',visibility:'visible',opacity:'1',...data.style},
    getBoundingClientRect:()=>{
      const [x,y,width,height]=data.rect||[20,60,400,30];
      return {x,y:y-scrollY,left:x,top:y-scrollY,right:x+width,bottom:y-scrollY+height,width,height};
    }};
  let next=null;
  for(const sibling of [...(data.following||[])].reverse()) {
    const node=element(sibling);node.nextElementSibling=next;next=node;
  }
  e.nextElementSibling=next;
  let child=e;
  for(const ancestor of data.ancestors||[]) {
    child.parentElement=element({...ancestor,tag:ancestor.tag||'DIV'});child=child.parentElement;
  }
  if(data.brParagraphs) {
    e.childNodes=[];
    for(const p of data.brParagraphs)e.childNodes.push({nodeType:3,textContent:p.text,_rect:p.rect,_parent:e},
      {nodeType:1,tagName:'BR',textContent:'',_parent:e},{nodeType:1,tagName:'BR',textContent:'',_parent:e});
    e.children=e.childNodes.filter(n=>n.nodeType===1);
  }
  return e;
}
const headings=(fixture.headings||[]).map(element),regions=(fixture.regions||[]).map(element);
globalThis.getComputedStyle=e=>e.style;
globalThis.document={readyState:'complete',images:[],body:{innerText:'Observed public fixture text'},title:'Fixture',
  createRange(){let start,end;const selected=()=>{const a=start._parent.childNodes;return a.slice(a.indexOf(start),a.indexOf(end)+1);};return {
    setStartBefore:n=>{start=n;},setEndAfter:n=>{end=n;},toString:()=>selected().map(n=>n.textContent).join(''),
    getBoundingClientRect:()=>{const rects=selected().filter(n=>n._rect).map(n=>n._rect);
      const x=Math.min(...rects.map(r=>r[0])),y=Math.min(...rects.map(r=>r[1]))-scrollY;
      const right=Math.max(...rects.map(r=>r[0]+r[2])),bottom=Math.max(...rects.map(r=>r[1]+r[3]))-scrollY;
      return {x,y,left:x,top:y,right,bottom,width:right-x,height:bottom-y};}};},
  querySelector:()=>null,querySelectorAll:selector=>{
    if(selector==='h1,h2,h3')return headings;
    if(selector==='div,dl,ul,ol,p')return (fixture.blocks||[]).map(element);
    if(selector==='p,li')return (fixture.paragraphs||[]).map(element);
    if(selector==='div,p')return (fixture.brBlocks||[]).map(element);
    if(selector==='figure,img,table,td,th,article,main,section,[role=main]')return [...regions,...(fixture.cells||[]).map(element)];
    if(selector==='a[href]')return [];
    if(selector==='iframe')return [];
    if(selector==='h1,h2,h3,figure,img,main')return [...headings,...regions];
    throw Error('Unexpected selector: '+selector);
  }};
const page={cdp:async()=>({result:{value:true}}),events:async()=>[],url:async()=>location.href,evaluate:async(fn)=>fn()};
globalThis.taskSpace=async()=>({spaceId:314,ownership:'agent',tabs:async()=>[{label:'p1',openedBy:'agent'}],page:()=>page});
const {run}=await import(HELPER);
for(const y of fixture.scrolls||[0]) {globalThis.scrollY=y;await run(REQUEST);}
'''
        script = harness.replace('FIXTURE',json.dumps(fixture)).replace('HELPER',json.dumps(helper)).replace('REQUEST',json.dumps(request.as_uri()))
        process = subprocess.run(['node','--input-type=module','-e',script],capture_output=True,text=True,encoding='utf-8',timeout=10)
        self.assertEqual(process.returncode,0,process.stderr)
        values = [json.loads(line.split(':',1)[1]) for line in process.stdout.splitlines() if line.startswith('EDITORIAL_JSON:')]
        self.assertEqual(len(values),len(fixture.get('scrolls',[0])),process.stdout)
        for value in values:
            self.assertTrue(value['ok'],value)
        return values

    @unittest.skipUnless(shutil.which('node'), 'Node is required for real observe DOM fixtures')
    def test_observe_filters_before_heading_cap_after_scroll(self):
        for preceding in (12,24):
            with self.subTest(preceding=preceding):
                ignored = [{'text':'Hidden navigation','style':{'visibility':'hidden'}} for _ in range(preceding//2)]
                ignored += [{'text':'Offscreen navigation','rect':[20,-100,400,30]} for _ in range(preceding//2)]
                before, after = self.observe_dom_fixture({'headings':ignored+[
                    {'text':'Actual carrier guidance','rect':[20,660,400,30],
                     'following':[{'tag':'P','text':'Actual carrier list','rect':[20,700,400,80]}]}], 'scrolls':[0,600]})
                self.assertEqual(before['regions'],[])
                self.assertEqual(after['scroll']['y'],600)
                self.assertEqual(after['regions'],[{'id':0,'tag':'EXCERPT',
                    'text':'Actual carrier guidance\nActual carrier list','credit':'',
                    'clip':{'x':20,'y':60,'width':400,'height':130}}])

    @unittest.skipUnless(shutil.which('node'), 'Node is required for real observe DOM fixtures')
    def test_observe_exposes_actual_formula_boxes_without_semantic_headings(self):
        text = 'Financial assets less 20000000, multiplied by 0.04 and divided by 12 months.'
        rows = self.observe_dom_fixture({'blocks':[{'tag':'DIV','text':text,'rect':[30,80,500,140]}]})[0]['regions']
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['tag'], 'CONTENT')
        self.assertEqual(rows[0]['text'], text)
        self.assertEqual(rows[0]['clip'], {'x':30,'y':80,'width':500,'height':140})

    def test_short_faq_paragraph_keeps_the_adjacent_qualification_in_crop(self):
        first='An actual official answer explaining the requested policy condition.'
        second='An adjacent qualification that must remain visible with the rule.'
        rows=self.observe_dom_fixture({'paragraphs':[{'tag':'P','text':first,'rect':[20,60,400,32],
                  'following':[{'tag':'P','text':second,'rect':[20,110,400,35]}]}]})[0]['regions']
        excerpt=next(r for r in rows if r['tag']=='PARAGRAPH_EXCERPT')
        self.assertIn(first,excerpt['text']);self.assertIn(second,excerpt['text'])
        self.assertEqual(excerpt['clip'],{'x':20,'y':60,'width':400,'height':85})

    def test_br_only_faq_answer_exposes_the_rule_with_its_qualification(self):
        first='A complete official answer stating the eligibility and guarantee rule.'
        second='A separate qualification about the application limits and assessment.'
        rows=self.observe_dom_fixture({'brBlocks':[{'tag':'DIV','rect':[20,20,400,300],
              'brParagraphs':[{'text':first,'rect':[20,60,400,30]},
                              {'text':second,'rect':[20,110,400,35]}]}]})[0]['regions']
        excerpt=next(r for r in rows if r['tag']=='BR_PARAGRAPH_EXCERPT')
        self.assertIn(first,excerpt['text']);self.assertIn(second,excerpt['text'])
        self.assertEqual(excerpt['clip'],{'x':20,'y':60,'width':400,'height':85})

    def test_long_paragraph_with_br_separators_exposes_visible_procedure(self):
        text='Login, select the insurance contract, select the hospital and visit, review and transmit.'
        rows=self.observe_dom_fixture({'brBlocks':[{'tag':'P','rect':[20,-1500,400,3000],
            'brParagraphs':[{'text':text,'rect':[20,60,400,64]},
                            {'text':'Read the complete public procedure before transmitting.','rect':[20,170,400,32]}]}]})[0]['regions']
        excerpt=next(r for r in rows if r['tag']=='BR_PARAGRAPH_EXCERPT')
        self.assertIn(text,excerpt['text'])
        self.assertEqual(excerpt['clip'],{'x':20,'y':60,'width':400,'height':142})

    def test_public_procedure_list_items_form_a_complete_readable_excerpt(self):
        text='Open the public result guide and follow the stated identity-check procedure.'
        rows=self.observe_dom_fixture({'paragraphs':[{'tag':'LI','text':text,'rect':[20,60,400,30],
            'following':[{'tag':'LI','text':'After verification, open the result list to inspect the application.','rect':[20,110,400,35]}]}]})[0]['regions']
        excerpt=next(r for r in rows if r['tag']=='PARAGRAPH_EXCERPT')
        self.assertIn(text,excerpt['text'])
        self.assertIn('After verification',excerpt['text'])
        self.assertEqual(excerpt['clip'],{'x':20,'y':60,'width':400,'height':85})

    def test_observe_includes_narrow_price_table_cells(self):
        rows=self.observe_dom_fixture({'cells':[{'tag':'TD','text':'Black Ink 54,000,000','rect':[20,40,210,200]}]})[0]['regions']
        self.assertEqual(rows[0]['tag'],'TD')
        self.assertIn('54,000,000',rows[0]['text'])
        self.assertEqual(rows[0]['clip']['width'],210)

    def test_only_public_bokjiro_screen_metadata_can_initialize_a_child_frame(self):
        helper = Path(e.__file__).with_name('editorial_browser.mjs').resolve().as_uri()
        script = """
import {publicScreenInitialization as allowed} from HELPER;
const parent='https://www.bokjiro.go.kr/ssis-tbu/twatbz/mkclAsis/mkclInsertBspnPage.do';
const p={resourceType:'Document',frameId:'child',request:{method:'POST',
url:'https://www.bokjiro.go.kr/ssis-tbu/twatbz/mkclAsis/mkclInsertBspnEmp.do',postData:'curScrId=screen&menuParam=menu&pageParam='}};
console.log(JSON.stringify([allowed(p,parent,'main'),
 allowed({...p,frameId:'main'},parent,'main'),
 allowed({...p,request:{...p.request,postData:p.request.postData+'&name=person'}},parent,'main'),
 allowed({...p,request:{...p.request,url:'https://www.bokjiro.go.kr/apply'}},parent,'main'),
 allowed(p,'https://other.example/page','main')]));
""".replace('HELPER', json.dumps(helper))
        result = subprocess.run(['node','--input-type=module','-e',script],capture_output=True,text=True,check=True)
        self.assertEqual(json.loads(result.stdout), [True,False,False,False,False])

    def test_observe_skips_blank_zero_size_hidden_and_script_text(self):
        rejected = [{'text':' \n\t'}, {'text':'Zero height','rect':[20,60,400,0]},
            {'text':'Zero width','rect':[20,60,0,30]},
            *[{'text':'Hidden heading','style':style} for style in (
                {'display':'none'},{'visibility':'hidden'},{'visibility':'collapse'},{'opacity':'0'})]]
        self.assertEqual(self.observe_dom_fixture({'headings':rejected})[0]['regions'],[])
        following = [{'tag':tag,'text':'Unrendered script text'} for tag in ('SCRIPT','STYLE','TEMPLATE','NOSCRIPT')]
        following += [{'tag':'P','text':'Hidden sibling','style':{'visibility':'hidden'}},
            {'tag':'P','text':'Zero height sibling','rect':[20,90,400,0]},
            {'tag':'P','text':'Observed paragraph','rect':[20,100,400,80]}]
        result = self.observe_dom_fixture({'headings':rejected+[{'text':'Evidence','following':following}]})[0]
        self.assertEqual([r['text'] for r in result['regions']],['Evidence\nObserved paragraph'])
        self.assertEqual(self.observe_dom_fixture({})[0]['regions'],[])

    @unittest.skipUnless(shutil.which('node'), 'Node is required for real observe DOM fixtures')
    def test_observe_preserves_region_path_ids_caps_and_viewport_clips(self):
        regions = [{'tag':'FIGURE','text':f'Existing figure {i}','rect':[0,0,100,100]} for i in range(41)]
        headings = [{'text':'Too little visible width','rect':[600,60,100,30]},
            {'text':'Offscreen left','rect':[-1,60,400,30]},
            {'text':'Below viewport','rect':[20,370,400,30]}]
        headings += [{'text':f'Excerpt {i}','rect':[500,250,300,30],
            'following':[{'tag':'P','text':'Source paragraph','rect':[500,290,300,200]}]} for i in range(15)]
        result = self.observe_dom_fixture({'headings':headings,'regions':regions})[0]['regions']
        self.assertEqual(len(result),52)
        self.assertEqual([r['id'] for r in result],list(range(52)))
        for i,r in enumerate(result[:40]):
            self.assertEqual(r,{'id':i,'tag':'FIGURE','text':f'Existing figure {i}','credit':f'Existing figure {i}',
                'clip':{'x':0,'y':0,'width':100,'height':100}})
        self.assertEqual([r['text'] for r in result[40:]],[f'Excerpt {i}\nSource paragraph' for i in range(12)])
        for r in result[40:]:
            self.assertEqual(r['clip'],{'x':500,'y':250,'width':140,'height':110})

    @unittest.skipUnless(shutil.which('node'), 'Node is required for real observe DOM fixtures')
    def test_observe_excludes_invisible_ancestors_and_semantic_navigation(self):
        ancestors = [[{'tag':'DIV'},{'style':{'opacity':'0'}}],
            [{'style':{'display':'none'}}], [{'tag':'DIV'},{'tag':'NAV'}],
            [{'tag':'DIV'},{'role':'navigation'}]]
        ignored = [{'text':'Not article evidence','ancestors':chain} for chain in ancestors]*3
        following = [{'tag':'SCRIPT','text':'Script instructions'},
            {'tag':'NAV','text':'Navigation menu'}, {'tag':'DIV','role':'navigation','text':'More navigation'},
            {'tag':'P','text':'Transparent content','ancestors':ancestors[0]},
            {'tag':'P','text':'Visible body text','rect':[20,100,400,80]}]
        result = self.observe_dom_fixture({'headings':ignored+[
            {'text':'Article heading','ancestors':[{'tag':'HEADER'}],'following':following}]})[0]['regions']
        self.assertEqual(len(result),1)
        self.assertEqual(result[0]['id'],0)
        self.assertEqual(result[0]['text'],'Article heading\nVisible body text')

    @unittest.skipUnless(shutil.which('node'), 'Node is required for fixed browser helper contract tests')
    def test_real_js_helper_network_gate_with_mocked_browser(self):
        helper = Path(e.__file__).with_name('editorial_browser.mjs').resolve().as_uri()
        request = self.folder/'request.json'
        request.write_text(json.dumps({'op':'observe','space':314,'url':'https://8.8.8.8/source'}),encoding='utf-8')
        harness = r'''
const actions=[];let navigated=false,sent=false,replaced=false,probed=false,loaded=false,loadSent=false;
const scenario=SCENARIO;
const page={
 label:'p1',
 snapshot:async()=>{actions.push({method:'snapshot'});if(scenario==='hung_renderer')throw Error('PageUnresponsiveError: renderer is probably hung');if(scenario==='unconfirmed_timeout')throw Error('snapshot transport unavailable');return {};},
 close:async()=>{actions.push({method:'close',label:page.label});},
 cdp:async(method,params)=>{actions.push({method,params});if(method==='Runtime.evaluate'&&navigated&&!loaded)throw Error('Readiness evaluated before pending load requests were serviced');if(method==='Page.getFrameTree'&&!probed&&['hung_renderer','unconfirmed_timeout','responsive_timeout'].includes(scenario)){probed=true;throw Error('Page.getFrameTree timed out');}return method==='Runtime.evaluate'?{result:{value:true}}:method==='Page.getFrameTree'?{frameTree:{frame:{id:'main'}}}:undefined;},
 events:async()=>{
   if(navigated&&sent&&scenario==='deferred_load'&&!loadSent){loadSent=true;loaded=true;return [{method:'Page.loadEventFired',params:{}}];}
   if(!navigated||sent)return [];
   sent=true;
   loaded=scenario!=='deferred_load';
   const pause=(id,url,method='GET',frameId='main')=>({method:'Fetch.requestPaused',params:{requestId:id,frameId,resourceType:'Document',request:{url,method,headers:{Cookie:'secret',Authorization:'secret',Accept:'text/html'}}}});
   return [pause('a','https://8.8.8.8/source',scenario==='post'?'POST':'GET'),
     ...(scenario==='private_redirect'?[pause('b','http://127.0.0.1/secret')]:[]),
     ...(scenario==='private_frame'?[pause('b','http://127.0.0.1/secret','GET','child')]:[]),
     {method:'Page.domContentEventFired',params:{}},...(loaded?[{method:'Page.loadEventFired',params:{}}]:[])];
 },
 evaluate:async(fn,arg)=>{
   if(arg){navigated=true;return true;}
   if(fn.toString().includes('document.readyState'))return true;
   if(fn.toString().includes('=>[scrollX'))return [0,0,[0,0,640,360]];
   return {url:'https://8.8.8.8/source',title:'Public',text:'Public source evidence',regions:[{id:0,tag:'FIGURE',text:'Public source evidence',credit:'',clip:{x:0,y:0,width:640,height:360}}],links:[],sensitive:false,scroll:{x:0,y:200}};
 },
 url:async()=>navigated||['capture','changed_region','same_source'].includes(scenario)?'https://8.8.8.8/source':'https://8.8.8.8/previous',screenshot:async(params)=>{actions.push({method:'screenshot',params});},
};
globalThis.listTaskSpaces=async()=>scenario==='shared_missing'?[]:[{id:314,name:'barolab-cf-flow',ownership:scenario==='shared_takeover'?'user':'agent'}];
globalThis.taskSpace=async()=>({spaceId:314,name:'barolab-cf-flow',ownership:scenario==='takeover'?'user':'agent',
 tabs:async()=>scenario==='ambiguous_page'?[{label:'p1',openedBy:'agent'},{label:'p2',openedBy:'agent'}]:
   ['shared_resume','shared_finish'].includes(scenario)?[{label:'p1',openedBy:'agent'},{label:'p2',openedBy:'agent'},{label:'u1',openedBy:'user'}]:
   [{label:replaced||scenario==='replaced_page'?'p2':'p1',openedBy:'agent',url:'https://8.8.8.8/source'}],
 newPage:async()=>{actions.push({method:'newPage',space:314});replaced=true;page.label='p2';return page;},
 page:label=>{if(label!==((replaced||scenario==='replaced_page'||['shared_resume','shared_finish'].includes(scenario))?'p2':'p1'))throw Error('Wrong page selected');page.label=label;return page;}});
await (await import(HELPER)).run(REQUEST);
console.log('ACTIONS:'+JSON.stringify(actions));
'''
        for scenario in ('public', 'deferred_load', 'private_frame', 'replaced_page', 'hung_renderer', 'unconfirmed_timeout', 'responsive_timeout', 'ambiguous_page', 'private_redirect', 'post', 'takeover', 'shared_new','shared_resume','shared_finish','shared_missing','shared_takeover', 'same_source', 'capture', 'changed_region'):
            request.write_text(e._json({'op':'observe','space':314,'url':'https://8.8.8.8/source'}),encoding='utf-8')
            if scenario.startswith('shared_'):
                request.write_text(e._json({'op':'finish' if scenario=='shared_finish' else 'observe',
                    'work_space_name':'barolab-cf-flow','page_label':'p2' if scenario in ('shared_resume','shared_finish') else None,
                    'url':'https://8.8.8.8/source'}),encoding='utf-8')
            if scenario in ('capture', 'changed_region'):
                request.write_text(e._json({'op':'capture','space':314,'url':'https://8.8.8.8/source',
                    'expected_text_sha256': e._hash(b'Public source evidence'), 'screenshot':str(self.folder/'clip.png'),
                    'region':{'id':0,'tag':'FIGURE','text':'Public source evidence','credit':'',
                        'clip':{'x':0,'y':0,'width':640 if scenario=='capture' else 641,'height':360}}}),encoding='utf-8')
            script = harness.replace('SCENARIO', json.dumps(scenario)).replace('HELPER', json.dumps(helper)).replace('REQUEST', json.dumps(request.as_uri()))
            process = subprocess.run(['node','--input-type=module','-e',script],capture_output=True,text=True,encoding='utf-8',timeout=10)
            self.assertEqual(process.returncode,0,process.stderr)
            lines = process.stdout.splitlines()
            value = json.loads(next(r.split(':',1)[1] for r in lines if r.startswith('EDITORIAL_JSON:')))
            actions = json.loads(next(r.split(':',1)[1] for r in lines if r.startswith('ACTIONS:')))
            if scenario == 'capture':
                self.assertTrue(value['ok'], value)
                self.assertEqual(next(a['params']['clip']['y'] for a in actions if a['method']=='screenshot'),200)
            elif scenario == 'changed_region':
                self.assertFalse(value['ok'])
                self.assertEqual(value['reason'],'source_changed')
            elif scenario=='ambiguous_page':
                self.assertFalse(value['ok'])
                self.assertEqual(actions,[])
            elif scenario=='unconfirmed_timeout':
                self.assertFalse(value['ok'])
                self.assertFalse(any(a['method'] in ('close','newPage') for a in actions))
                self.assertEqual(sum(a['method']=='Page.getFrameTree' for a in actions),1)
            elif scenario=='same_source':
                self.assertTrue(value['ok'],value)
                self.assertFalse(any(a['method']=='Fetch.continueRequest' for a in actions))
            elif scenario.startswith('shared_'):
                self.assertEqual(value['ok'],scenario not in ('shared_missing','shared_takeover'),value)
                if scenario in ('shared_missing','shared_takeover'):
                    self.assertEqual(actions,[])
                elif scenario=='shared_finish':
                    self.assertTrue(value['workingSpacePreserved'])
                    self.assertEqual(actions,[{'method':'close','label':'p2'}])
                else:
                    self.assertEqual(value['page'],'p2')
                    self.assertEqual(sum(a['method']=='newPage' for a in actions),int(scenario=='shared_new'))
                    self.assertFalse(any(a['method']=='close' for a in actions))
            elif scenario in ('public','deferred_load','private_frame','replaced_page','hung_renderer','responsive_timeout'):
                self.assertTrue(value['ok'])
                headers = next(a['params']['headers'] for a in actions if a['method']=='Fetch.continueRequest')
                self.assertEqual(headers,[{'name':'Accept','value':'text/html'}])
                if scenario=='private_frame':
                    self.assertTrue(value['blockedDocuments'])
                    self.assertTrue(any(a['method']=='Fetch.failRequest' for a in actions))
                if scenario=='hung_renderer':
                    self.assertTrue(value['rendererRecovery']['sameTaskspace']==314)
                    self.assertEqual([a['method'] for a in actions if a['method'] in ('snapshot','close','newPage')],['snapshot','close','newPage'])
                else:
                    self.assertFalse(any(a['method'] in ('close','newPage') for a in actions))
            else:
                self.assertFalse(value['ok'])
                self.assertEqual(value['reason'],'user_takeover' if scenario=='takeover' else 'unsafe_navigation')
                if scenario == 'takeover':
                    self.assertEqual(actions,[])
                else:
                    self.assertIn('Fetch.failRequest',[a['method'] for a in actions])

    def test_jev_visual_gate_and_section1_flow_policy(self):
        from dashboard.common import jev
        # Section 1 (cap_idx == 0) must never route to Flow illustration even if has_browser_capture is True
        self.assertFalse(e._should_use_flow_for_section('삼쩜삼 병원비 환급금', {'heading': '신청 전 3초 판독', 'body': '일반 안내 문단'}, {'query': '삼쩜삼', 'subject': '환급'}, 0, 3, True))
        # Checklist / portal UI sections must never route to Flow illustration even in later sections
        self.assertFalse(e._should_use_flow_for_section('삼쩜삼 병원비 환급금', {'heading': '실제 입금액 비교표', 'body': '일반 안내 문단'}, {'query': '삼쩜삼', 'subject': '비교표'}, 1, 3, True))
        # Non-first lifestyle section after a real browser capture can use Flow
        self.assertTrue(e._should_use_flow_for_section('삼쩜삼 병원비 환급금', {'heading': '보관 루틴과 정리 방법', 'body': '평소 서랍에 영수증을 모아두면 편합니다.'}, {'query': '영수증 보관', 'subject': '보관 루틴'}, 2, 3, True))
        # JEV inspect_published_visual requires all 3 noul checks >= 0.55
        with unittest.mock.patch.object(jev, 'prepare_image_asset', return_value={'asset': {'data': 'x'}}), \
             unittest.mock.patch.object(jev, '_ask', return_value={
                 'status': 'ok',
                 'answers': {
                     'readableAndUnclipped': {'type': 'noul', 'noul': 0.91},
                     'noAiGibberishOrAdBanner': {'type': 'noul', 'noul': 0.92},
                     'koreanContextFit': {'type': 'noul', 'noul': 0.12},
                 },
             }):
            res = jev.inspect_published_visual('dummy.png', title='삼쩜삼 병원비 환급금')
            self.assertFalse(res['passed'])


REAL_BROWSER = e._Browser
REAL_MODEL = e._model

if __name__ == '__main__':
    unittest.main()
