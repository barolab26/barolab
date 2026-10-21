import copy
import hashlib
import json
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from naver_blog_posting import pipeline_runner as r
from naver_blog_posting.material_assets import _digest

class SourceCaptureRepairTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.folder=Path(self.tmp.name)/'output/soultin/run';(self.folder/'images').mkdir(parents=True)
        self.plan={'filename':'example.jpg','source':'generated','purpose':'Exact six ages','afterBlock':1}
        Image.new('RGB',(300,300),'blue').save(self.folder/'images/example.jpg')
        self.write('image-plan.json',{'imagePlans':[self.plan]})
        self.write('reviewer-model-events.json',[{'state':'returned','actual_model':'actual'}])
        self.record={'status':'rejected','imageSha256':r.sha(self.folder/'images/example.jpg'),'planSha256':_digest(self.plan),
            'review':{'passed':False,'issues':['Six age labels not readable']}}
        self.name='visual-reviews/reviewer/group_0.json';self.write(self.name,self.record)
    def write(self,name,value):
        path=self.folder/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value),encoding='utf-8')
    def failure(self):return r.VisualPixelsRejected(self.folder,str(Path(self.name)),r.sha(self.folder/self.name))
    def test_refusal_bound_to_actual_image_plan_and_model_event(self):
        r.rejected_visual_evidence(self.folder)
        self.write(self.name,{**self.record,'planSha256':'0'*64})
        with self.assertRaises(RuntimeError):r.rejected_visual_evidence(self.folder)
        self.write(self.name,self.record);self.write('reviewer-model-events.json',[])
        with self.assertRaises(RuntimeError):r.rejected_visual_evidence(self.folder)
    def test_stale_failure_cannot_claim_budget(self):
        failure=self.failure();self.write(self.name,{**self.record,'review':{'passed':False,'issues':['changed']}})
        with patch.object(r,'claim_repair_budget') as claim,self.assertRaises(RuntimeError):
            r.repair_source_capture_once('soultin',self.folder,failure)
        claim.assert_not_called()
    def test_fresh_entry_routes_exact_typed_refusal_to_shared_repair(self):
        failure=self.failure()
        with patch.object(r,'repair_source_capture_once',return_value='prepared') as repair:
            self.assertEqual(r.repair_preparation_once('soultin',None,None,True,'11:00',failure),'prepared')
            repair.assert_called_once_with('soultin',failure.folder,failure,True)
    def test_existing_budget_claim_is_mandatory_before_any_capture_or_model(self):
        self.write('preparation-context.json',{'publicationDate':'2026-10-22','scheduledSlot':'11:00'})
        handoff=types.SimpleNamespace(check=lambda:[{}]*5)
        with patch.object(r,'AgentHandoff',return_value=handoff),patch.object(r,'claim_repair_budget',side_effect=RuntimeError('Wrong lock/worker or exhausted')) as claim,patch.object(r,'generate_content_json') as model:
            with self.assertRaises(r.MaterialRequired):r.repair_source_capture_once('soultin',self.folder,self.failure(),True)
            self.assertTrue(claim.call_args.args[-1]);model.assert_not_called()
    def test_format_correction_preserves_semantics_and_valid_anchors(self):
        text='official table heading short123456 tail short other'
        source={'url':'https://example.gov/table','text':text,'bodySha256':hashlib.sha256(text.encode()).hexdigest()}
        candidate={'kind':'source_capture','caption':'Exact caption','purpose':'Exact purpose','alt':'Exact alt',
            'request':{'sourceUrl':source['url'],'anchors':['official table heading','short'],'materialId':'same','stepId':'same','observation':'same'}}
        with patch.object(r,'bind_official_capture_requests') as bind:
            corrected=r.normalize_short_capture_anchors(candidate,[source],['official table heading','short123456'])
            self.assertEqual(candidate['request']['anchors'][1],'short')
            for key in ('caption','purpose','alt'):self.assertEqual(corrected[key],candidate[key])
            self.assertEqual(corrected['request']['sourceUrl'],source['url']);bind.assert_called_once()
            ignored=r.normalize_short_capture_anchors(candidate,[source],['unauthorized model change','short123456'])
            self.assertEqual(ignored['request']['anchors'][0],candidate['request']['anchors'][0])
            for bad in (['official table heading','other'],['official table heading','new unsupported text']):
                with self.assertRaises(RuntimeError):r.normalize_short_capture_anchors(candidate,[source],bad)

    def test_capture_rejection_preserves_original_error(self):
        original=ValueError('Actual image review rejected: unreadable capture')
        with patch.object(r,'rejected_visual_evidence',side_effect=RuntimeError('generated only')):
            with self.assertRaises(ValueError) as raised:r.raise_current_pixel_refusal(self.folder,{},original)
        self.assertIs(raised.exception,original)

    def test_host_provenance_requires_matching_source_body_and_image(self):
        body='Actual official age table body'
        source={'url':'https://www.mohw.go.kr/menu.es?mid=a10714010200','text':body,'bodySha256':hashlib.sha256(body.encode()).hexdigest()}
        row={'materialId':'official','source':'capture','sourceUrl':source['url'],'sourceBodySha256':source['bodySha256'],
            'filePath':str(self.folder/'images/example.jpg'),'sha256':r.sha(self.folder/'images/example.jpg'),
            'observedText':body,'capturedAt':'2026-10-21T00:00:00+00:00'}
        context=r.publication_visual_context(self.folder,{}, {'materials':[row]},[source])
        self.assertEqual(len(context['hostVerifiedCaptureProvenance']),1)
        with self.assertRaises(RuntimeError):r.publication_visual_context(self.folder,{}, {'materials':[{**row,'sourceBodySha256':'0'*64}]},[source])

    def test_source_identity_contract_only_with_exact_verified_pixels(self):
        from naver_blog_posting.material_assets import review_visual_groups
        plan={**self.plan,'source':'capture','materialId':'official'};image=self.folder/'images/example.jpg'
        evidence={'materialId':'official','imageSha256':r.sha(image),'sourceUrl':'https://www.mohw.go.kr/','sourceBodySha256':'a'*64}
        requests=[]
        def judge(request,paths,schema):
            requests.append(request);return {'passed':True,'observation':'All six values readable','issues':[]}
        review_visual_groups([plan],[image],judge,{'hostVerifiedCaptureProvenance':[evidence]},self.folder/'reviews','verified')
        self.assertIn('HOST-VERIFIED CAPTURE PROVENANCE:',requests[-1])
        review_visual_groups([plan],[image],judge,{'hostVerifiedCaptureProvenance':[{**evidence,'imageSha256':'0'*64}]},self.folder/'reviews','unverified')
        self.assertNotIn('HOST-VERIFIED CAPTURE PROVENANCE:',requests[-1])
        def reject(request,paths,schema):return {'passed':False,'observation':'Unreadable','issues':['Missing values']}
        with self.assertRaises(ValueError):review_visual_groups([plan],[image],reject,{'hostVerifiedCaptureProvenance':[evidence]},self.folder/'reviews','rejected')

    def test_provenance_contract_re_review_is_one_time(self):
        self.write('preparation-context.json',{'publicationAttempt':False})
        self.write('visual-provenance-rereview.json',{'status':'previous attempt'})
        with patch.object(r,'BASE_DIR',Path(self.tmp.name)),patch.object(r,'_prepare_content') as prepare:
            with self.assertRaisesRegex(RuntimeError,'already attempted'):
                r.rereview_corrected_visual_preparation('soultin',self.folder)
            prepare.assert_not_called()

    def test_assembler_schema_binds_reviewed_positions_including_zero_images(self):
        for slots in ([2,4,8],[]):
            schema=r.agent_output_schema('assembler',image_slots=slots)
            self.assertEqual(schema['properties']['imageSlots']['enum'],[slots])
        self.assertNotEqual(r.agent_output_schema('assembler',image_slots=[2,4,8])['properties']['imageSlots']['enum'],[[2,5,8]])

    def final_validation_fixture(self, approved=True, changed_bytes=False, missing_provenance=False):
        from contextlib import ExitStack
        self.write('article.json',{'title':'Original approved title','blocks':[{'kind':'paragraph','text':'Actual approved answer body'}]})
        self.write('review.json',{'articleSha256':r.sha(self.folder/'article.json')})
        self.write('writer-demand-alignment.json',{})
        selection={'readerQuestion':'What is the actual age?'};self.write('keyword-selector.json',selection)
        body='Official exact age table';source={'url':'https://www.mohw.go.kr/menu.es?mid=a10714010200','text':body,'bodySha256':hashlib.sha256(body.encode()).hexdigest()}
        self.write('sources.json',[source])
        row={'materialId':'official','stepId':'age','source':'capture','filename':'example.jpg',
            'filePath':str(self.folder/'images/example.jpg'),'sha256':'0'*64 if changed_bytes else r.sha(self.folder/'images/example.jpg'),
            'sourceUrl':source['url'],'sourceBodySha256':source['bodySha256'],'capturedAt':'2026-10-21T00:00:00+00:00',
            'sensitiveDataAbsent':True,'observation':body,'observedText':body}
        if missing_provenance:row.pop('sourceBodySha256')
        self.write('supplemental-visual-materials.json',{'version':1,'account':'soultin','readerQuestion':selection['readerQuestion'],'materials':[row]})
        image_stage={'agent':'image-maker','fileHashes':{'source-capture-repair.json':'audit'}}
        if approved:image_stage['fileHashes']['supplemental-visual-materials.json']='accepted packet'
        handoff=types.SimpleNamespace(folder=self.folder,data={'stages':[image_stage]},check=lambda **kwargs:None,file=lambda name:self.folder/name)
        stack=ExitStack()
        stack.enter_context(patch.object(r,'AgentHandoff',return_value=handoff))
        stack.enter_context(patch.object(r,'material_roots',return_value=[Path(self.tmp.name)/'output']))
        for name in ('require_content_review','require_answer_plan_handoff','validate_answer_audit','validate_reader_demand_alignment'):
            stack.enter_context(patch.object(r,name))
        stack.enter_context(patch.object(r,'require_reader_demand_handoff',return_value=selection))
        self.addCleanup(stack.close)

    def test_final_publication_validation_rejects_unaccepted_supplement(self):
        self.final_validation_fixture(approved=False)
        with self.assertRaisesRegex(RuntimeError,'not accepted'):
            r.require_content_handoff(self.folder,'soultin')

    def test_final_publication_validation_rejects_changed_capture_bytes(self):
        self.final_validation_fixture(changed_bytes=True)
        with self.assertRaisesRegex(r.MaterialRequired,'bytes changed'):
            r.require_content_handoff(self.folder,'soultin')

    def test_final_publication_validation_rejects_missing_source_provenance(self):
        self.final_validation_fixture(missing_provenance=True)
        with self.assertRaisesRegex(RuntimeError,'Every supplemental capture'):
            r.require_content_handoff(self.folder,'soultin')

    def test_saved_entry_uses_same_shared_repair_and_restores_options(self):
        context={'publicationAttempt':False,'runOptions':{'publication_date':'2026-10-22'}};self.write('preparation-context.json',context)
        from contextlib import nullcontext
        original=copy.deepcopy(r.RUN_OPTIONS)
        with patch.object(r,'BASE_DIR',Path(self.tmp.name)),patch.object(r,'pipeline_lock',return_value=nullcontext()),patch.object(r,'repair_source_capture_once',return_value='prepared') as repair:
            self.assertEqual(r.repair_rejected_visual_preparation('soultin',self.folder),'prepared')
            self.assertFalse(repair.call_args.args[-1])
        self.assertEqual(r.RUN_OPTIONS,original)

if __name__=='__main__':unittest.main()
