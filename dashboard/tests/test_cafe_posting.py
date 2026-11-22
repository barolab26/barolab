import copy
import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

from naver_cafe_posting import editorial, posting


class CafePostingTests(unittest.TestCase):
    def setUp(self):
        text = 'Observed primary source with the current eligibility and application steps.'
        self.research = {'collectedAt':datetime.now(timezone.utc).isoformat(), 'sources':[
            {'url':'https://www.hf.go.kr/ko/detail.do','status':200,'text':text,
             'textSha256':hashlib.sha256(text.encode()).hexdigest()}]}
        self.doc = {'title':'주택연금 가입조건 확인', 'readerTask':'현재 가입 조건과 신청 절차 확인',
            'audienceTags':['finance'], 'blocks':[{'type':'text','text':'주택연금 가입조건은 나이와 주택 요건을 먼저 확인합니다.'},
            {'type':'heading','text':'신청 전 확인'}, {'type':'table','rows':[['상황','확인'],['가입 예정','공식 안내 대조']]}],
            'lineLinks':{},'relatedLinks':[]}

    def test_full_article_keeps_last_block_and_table(self):
        spec=posting._build_cafe_post_payload('boutiqueinfo', {'document':self.doc,'research':self.research})
        self.assertIn('공식 안내 대조',spec['contentHtml'])
        self.assertIn('<table',spec['contentHtml'])
        self.assertNotIn('https://www.meganote.kr',spec['contentHtml'])

    def test_legacy_snippets_cannot_publish(self):
        with self.assertRaises(ValueError):
            posting._build_cafe_post_payload('boutiqueinfo',{'title':'old','paragraphs':['truncated']},'https://wrong.example/')

    def test_three_posts_never_unlock_links(self):
        q=posting.evaluate_cafe_safety_quota('boutiqueinfo',[{'cafeId':'boutiqueinfo','hasExternalLink':False}]*3)
        self.assertFalse(q['bridgeUnlocked'])
        self.assertEqual(q['nextPostMode'],'reader_complete')

    def test_unknown_and_suspended_cafes_hold(self):
        for cafe in ('loveshake1','dekilab','unknown'):
            with self.assertRaises(ValueError):editorial.validate_document(self.doc,self.research,cafe)

    def test_finance_does_not_fit_ai_cafe(self):
        active_policy={**posting.CAFE_POLICIES['dekilab'],'policyMode':'reader_complete'}
        with patch.dict(posting.CAFE_POLICIES,{'dekilab':active_policy}):
            with self.assertRaisesRegex(ValueError,'audience'):
                editorial.validate_document(self.doc,self.research,'dekilab')

    def test_observed_dekilab_restriction_remains_held(self):
        q=posting.evaluate_cafe_safety_quota('dekilab',[])
        self.assertEqual(q['nextPostMode'],'held')
        self.assertEqual(q['restrictionUntil'],'2026-11-24')

    def test_stale_or_mutated_source_holds(self):
        for data in (copy.deepcopy(self.research),copy.deepcopy(self.research)):
            data['sources'][0]['text']='changed'
            with self.assertRaises(ValueError):editorial.validate_document(self.doc,data,'boutiqueinfo')
        self.research['collectedAt']=(datetime.now(timezone.utc)-timedelta(hours=7)).isoformat()
        with self.assertRaises(ValueError):editorial.validate_document(self.doc,self.research,'boutiqueinfo')

    def test_required_capture_is_not_silently_dropped(self):
        self.doc['requiredCaptures']=['application step']
        with self.assertRaisesRegex(ValueError,'capture'):
            editorial.validate_document(self.doc,self.research,'boutiqueinfo')

    def test_link_requires_exact_observed_destination_and_value(self):
        self.doc['blocks'].append({'type':'text','text':'공식 조건 상세'})
        self.doc['lineLinks']={'공식 조건 상세':'https://www.hf.go.kr/ko/detail.do'}
        with self.assertRaises(ValueError):editorial.validate_document(self.doc,self.research,'boutiqueinfo')
        self.doc['relatedLinks']=[{'label':'공식 조건 상세','url':'https://www.hf.go.kr/ko/detail.do','additionalValue':'세부 예외'}]
        editorial.validate_document(self.doc,self.research,'boutiqueinfo')
        self.assertIn('href="https://www.hf.go.kr/ko/detail.do"',editorial.render(self.doc))
        self.assertIn('text-decoration:underline',editorial.render(self.doc))

    def test_owned_link_disclosure_must_be_visible(self):
        self.doc['blocks'].append({'type':'text','text':'공식 조건 상세'})
        self.doc['lineLinks']={'공식 조건 상세':'https://www.hf.go.kr/ko/detail.do'}
        self.doc['relatedLinks']=[{'label':'공식 조건 상세','url':'https://www.hf.go.kr/ko/detail.do','additionalValue':'세부 예외','owned':True,'disclosure':'직접 운영'}]
        with self.assertRaises(ValueError):editorial.validate_document(self.doc,self.research,'boutiqueinfo')

    def test_link_cannot_be_executable_even_if_supplied_as_a_source(self):
        url='javascript:alert(1)'
        self.doc['blocks'].append({'type':'text','text':'상세 자료'})
        self.doc['lineLinks']={'상세 자료':url}
        self.doc['relatedLinks']=[{'label':'상세 자료','url':url,'additionalValue':'details'}]
        self.research['sources'][0]['url']=url
        with self.assertRaises(ValueError):editorial.validate_document(self.doc,self.research,'boutiqueinfo')

    def test_article_identity_rejects_other_service_or_ambiguous_url(self):
        self.assertEqual(editorial.article_identity('https://cafe.naver.com/ca-fe/cafes/31608088/articles/2410')['articleId'],'2410')
        for url in ('https://blog.naver.com/a/2410','https://cafe.naver.com/ca-fe/cafes/31608088/articles/2410/modify','https://cafe.naver.com/ca-fe/cafes/31608088/articles/2410?other=1'):
            with self.assertRaises(ValueError):editorial.article_identity(url)

    def test_scheduler_does_not_create_posts_without_prepared_work(self):
        with patch.object(posting,'load_cafe_status',return_value={}),patch.object(posting,'publish_cafe_bridge_part') as publish:
            posting.process_cafe_autonomy_once()
            publish.assert_not_called()

    def test_unavailable_records_are_not_success_or_republished(self):
        status={'publishedArticles':[{'cafeId':'boutiqueinfo','part':6,'articleUrl':'https://cafe.naver.com/boutiqueinfo/2340','publicState':'unavailable'}]}
        with patch.object(posting,'load_cafe_status',return_value=status):
            result=posting.publish_cafe_bridge_part(6)
        self.assertFalse(result['ok'])
        self.assertEqual(result['receipts'][0]['publicState'],'unavailable')

    def test_legacy_browser_entry_point_requires_reviewed_artifact(self):
        from dashboard.common.ego_taskspace import native_publish_naver_cafe_article
        with self.assertRaises(ValueError):native_publish_naver_cafe_article('soul5373','31608088','4','old',['old'])

    def test_encoded_receipt_aliases_do_not_inflate_post_count(self):
        rows=[{'cafeId':'boutiqueinfo','articleUrl':'https://cafe.naver.com/boutiqueinfo/2340','id':'old'},
              {'cafeId':'boutiqueinfo','articleUrl':'https://cafe.naver.com/boutiqueinfo?iframe_url_utf8=%2Fca-fe%2Fcafes%2F31608088%2Farticles%2F2340','id':'new','publicState':'body_verified'},
              {'cafeId':'boutiqueinfo','articleUrl':'https://cafe.naver.com/boutiqueinfo/2305','id':'distinct'}]
        actual=posting.normalize_articles(rows)
        self.assertEqual(len(actual),2)
        self.assertEqual(actual[0]['publicState'],'body_verified')
        self.assertEqual(actual[0]['legacyRecordAliases'][0]['id'],'old')
        self.assertEqual(posting.normalize_articles(actual),actual)

    def test_only_official_semas_notices_and_bundles_are_primary(self):
        from dashboard.common.content_improvement import primary_url
        self.assertTrue(primary_url('https://www.sbiz24.kr/#/pbanc/567'))
        self.assertTrue(primary_url('https://www.sbiz24.kr/api/cmmn/file/zip/pbancdoc-567/download.zip'))
        self.assertFalse(primary_url('https://www.sbiz24.kr/#/community/567'))
        self.assertFalse(primary_url('https://sbiz24.kr.attacker.example/#/pbanc/567'))


if __name__=='__main__':unittest.main()
