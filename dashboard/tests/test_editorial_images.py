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
    failure = None
    def __init__(self, directory, name):
        self.space = 123
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
            'subject': 'screen capture', 'event': '', 'date': '', 'reason': 'shows actual instructions'} for r in payload['sections']]}
    elif stage == 'source':
        result = {'index': 0}
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

    def test_manifest_mutation_is_rejected(self):
        result = self.build()
        result['assets'][0]['caption'] = 'Wrong event'
        (self.folder/e.MANIFEST).write_text(json.dumps(result), encoding='utf-8')
        self.assertFalse(self.valid(result))

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

    def test_injection_code_is_never_executed(self):
        def malicious(*args):
            result, receipt = model(*args)
            if args[0] == 'source':
                result = {'index': '__import__("os").system("anything")'}
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
            return result, receipt
        with patch.object(e, '_model', omitted):
            required = self.build()
            self.assertEqual(required['reasons'], ['required_image_omitted'])
            with tempfile.TemporaryDirectory() as directory:
                optional = [{**SECTION[0], 'image_optional': True}]
                value = e.build_editorial_assets('Capture guide', optional, directory)
                self.assertEqual(value['reasons'], ['no_required_editorial_asset'])
                self.assertFalse(e.validate_editorial_assets('Capture guide', optional, directory, value))
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
  const e={tagName:data.tag||'H2',role:data.role,innerText:data.text??'Visible source heading',
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
  return e;
}
const headings=(fixture.headings||[]).map(element),regions=(fixture.regions||[]).map(element);
globalThis.getComputedStyle=e=>e.style;
globalThis.document={body:{innerText:'Observed public fixture text'},title:'Fixture',
  querySelector:()=>null,querySelectorAll:selector=>{
    if(selector==='h1,h2,h3')return headings;
    if(selector==='figure,img,table,article,main,section,[role=main]')return regions;
    if(selector==='a[href]')return [];
    if(selector==='h1,h2,h3,figure,img,main')return [...headings,...regions];
    throw Error('Unexpected selector: '+selector);
  }};
const page={cdp:async()=>{},url:async()=>location.href,evaluate:async(fn)=>fn()};
globalThis.taskSpace=async()=>({spaceId:314,ownership:'agent',page:()=>page});
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
const actions=[];let navigated=false,sent=false;
const scenario=SCENARIO;
const page={
 cdp:async(method,params)=>{actions.push({method,params});},
 events:async()=>{
   if(!navigated||sent)return [];
   sent=true;
   const pause=(id,url,method='GET')=>({method:'Fetch.requestPaused',params:{requestId:id,resourceType:'Document',request:{url,method,headers:{Cookie:'secret',Authorization:'secret',Accept:'text/html'}}}});
   return [pause('a','https://8.8.8.8/source',scenario==='post'?'POST':'GET'),
     ...(scenario==='private_redirect'?[pause('b','http://127.0.0.1/secret')]:[]),
     {method:'Page.domContentEventFired',params:{}}];
 },
 evaluate:async(fn,arg)=>{
   if(arg){navigated=true;return true;}
   if(fn.toString().includes('document.readyState'))return true;
   if(fn.toString().includes('=>[scrollX'))return [0,0,[0,0,640,360]];
   return {url:'https://8.8.8.8/source',title:'Public',text:'Public source evidence',regions:[{id:0,tag:'FIGURE',text:'Public source evidence',credit:'',clip:{x:0,y:0,width:640,height:360}}],links:[],sensitive:false,scroll:{x:0,y:200}};
 },
 url:async()=>'https://8.8.8.8/source',screenshot:async(params)=>{actions.push({method:'screenshot',params});},
};
globalThis.taskSpace=async()=>({spaceId:314,ownership:scenario==='takeover'?'user':'agent',page:()=>page});
await (await import(HELPER)).run(REQUEST);
console.log('ACTIONS:'+JSON.stringify(actions));
'''
        for scenario in ('public', 'private_redirect', 'post', 'takeover', 'capture', 'changed_region'):
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
            elif scenario == 'public':
                self.assertTrue(value['ok'])
                headers = next(a['params']['headers'] for a in actions if a['method']=='Fetch.continueRequest')
                self.assertEqual(headers,[{'name':'Accept','value':'text/html'}])
            else:
                self.assertFalse(value['ok'])
                self.assertEqual(value['reason'],'user_takeover' if scenario=='takeover' else 'unsafe_navigation')
                if scenario == 'takeover':
                    self.assertEqual(actions,[])
                else:
                    self.assertIn('Fetch.failRequest',[a['method'] for a in actions])


REAL_BROWSER = e._Browser
REAL_MODEL = e._model

if __name__ == '__main__':
    unittest.main()
