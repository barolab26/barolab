"""Reader decisions, link provenance and nullable performance observations."""
import copy
import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

from common import naver_reader as reader
from naver_blog_posting import posting


def observed_source(url):
    text='Observed official instructions for the reader.'
    return {'url':url,'status':200,'text':text,'textSha256':hashlib.sha256(text.encode()).hexdigest()}


class NaverReaderTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.doc={'title':'Example reader question','published':False,'blocks':[
            {'type':'heading','text':'Answer'}, {'type':'text','text':'The exact answer lets the reader act correctly.'},
            {'type':'tags','text':'#Example'}]}

    def test_fifth_required_section_is_not_demoted_to_meet_a_quota(self):
        self.doc['blocks']=[b for i in range(5) for b in (
            {'type':'heading','text':str(i)}, {'type':'text','text':'Actual screen '+str(i)})]
        self.doc['editorialSectionOptions']={f'section-{i}':False for i in range(1,6)}
        self.assertEqual(sum(not s['image_optional'] for s in posting.naver_image_sections(self.doc)),5)

    def test_unspecified_sections_are_reader_choices_not_implicit_required_images(self):
        self.assertTrue(all(s['image_optional'] for s in posting.naver_image_sections(self.doc)))
        self.doc['blocks']=[{'type':'text','text':'A complete short answer.'}]
        self.assertTrue(posting.naver_image_sections(self.doc)[0]['image_optional'])

    def test_guide_sync_uses_the_same_reader_policy_and_preserves_no_legacy_naver_quota(self):
        from common.knowledge_policy import sync_second_brain_guides
        sync_second_brain_guides(self.root)
        guide=next((self.root/'dashboard/data/second_brain').glob('02*')).read_text(encoding='utf-8')
        section=guide.split('## 3. 네이버 블로그',1)[1].split('## 4.',1)[0]
        self.assertIn(reader.POLICY,section)
        self.assertNotIn('외부 링크 0개',section)
        self.assertNotIn('15~18자',section)
        path=next((self.root/'dashboard/data/second_brain').glob('02*'))
        path.write_text(guide+'\n<!-- naver-reader-policy-20261105:start -->\nTemporary compatibility policy\n<!-- naver-reader-policy-20261105:end -->\nUser note preserved\n',encoding='utf-8')
        sync_second_brain_guides(self.root)
        refreshed=path.read_text(encoding='utf-8')
        self.assertNotIn('Temporary compatibility policy',refreshed)
        self.assertIn('User note preserved',refreshed)

    def test_zero_images_has_no_fake_representative_and_still_validates_text(self):
        plan={'version':1,'main_keyword':'Example','signoff':'','representative_file':'','assets':[]}
        self.assertTrue(posting.validate_document(self.doc,plan,self.root)['ok'])
        bad=copy.deepcopy(self.doc);bad['blocks'].insert(2,{'type':'image','id':0,'file':'missing.png','alt':'Real image','caption':'Real source'})
        self.assertFalse(posting.validate_document(bad,plan,self.root)['ok'])
        self.assertIsNone(posting._validate_plan({**plan,'representative_file':'fake.png'}))

    def test_observed_official_link_remains_native_link_on_any_account(self):
        url='https://www.nts.go.kr/guide'
        self.doc['blocks'][1]['text']='Use the official instructions.\n[Official application guide]('+url+')'
        reader.normalize_links(self.doc,[observed_source(url)],allow_external=True)
        self.assertEqual(self.doc['lineLinks'],{'Official application guide':url})
        self.assertNotIn('https://',self.doc['blocks'][1]['text'])

    def test_inline_observed_link_becomes_a_clickable_native_paragraph(self):
        url='https://www.nts.go.kr/guide'
        self.doc['blocks'][1]['text']='Read [Official guide]('+url+') before applying.'
        reader.normalize_links(self.doc,[observed_source(url)],allow_external=True)
        self.assertIn('Official guide',self.doc['blocks'][1]['text'].splitlines())
        self.assertEqual(self.doc['lineLinks']['Official guide'],url)

    def test_search_snippet_or_tampered_source_cannot_authorize_a_link(self):
        url='https://www.nts.go.kr/guide'
        self.doc['blocks'][1]['text']='[Official guide]('+url+')'
        with self.assertRaisesRegex(ValueError,'unobserved'):
            reader.normalize_links(self.doc,[{'url':url,'title':'Search snippet only'}],allow_external=True)
        with self.assertRaisesRegex(ValueError,'unobserved'):
            reader.normalize_links(self.doc,[{**observed_source(url),'text':'tampered'}],allow_external=True)

    def test_external_links_are_off_by_default_even_for_observed_official_sources(self):
        url='https://www.nts.go.kr/guide'
        self.doc['blocks'][1]['text']='[Official guide]('+url+')'
        with self.assertRaisesRegex(ValueError,'separate instruction'):
            reader.normalize_links(self.doc,[observed_source(url)])

    def test_unobserved_and_unrelated_links_do_not_silently_survive(self):
        self.doc['blocks'][1]['text']='Use the exact answer.\nUnrelated benefit'
        self.doc['lineLinks']={'Unrelated benefit':'https://example.org/other-benefit'}
        with self.assertRaisesRegex(ValueError,'relevance'):
            reader.normalize_links(self.doc,[],allow_external=True)

    def test_writer_cannot_self_approve_a_new_link(self):
        self.doc['blocks'][1]['text']='[Apply](https://example.org/apply)'
        self.doc['relatedLinkReview']={'relevant':True,'reason':'writer says so','observedTitle':'Apply','url':'https://example.org/apply'}
        with self.assertRaisesRegex(ValueError,'unobserved'):
            reader.normalize_links(self.doc,[],allow_external=True)

    def review(self, **changes):
        response={**dict.fromkeys(('titleFulfilled','currentEvidence','actionableAnswer','branchesConsistent',
            'noUnsupportedExperience','linksRelevant','noRedundantPadding'),True),'status':'passed',
            'issues':[],'evidenceQuotes':['The exact answer lets the reader act correctly.'],**changes}
        (self.root/'research.json').write_text(json.dumps({'sources':[{'url':'https://example.org','text':'Observed text'}]}),encoding='utf-8')
        generate=lambda *a,**kw:response
        return reader.ensure_reader_review(self.doc,self.root,generate)

    def test_negative_independent_reader_decision_is_preserved_and_blocks(self):
        with self.assertRaisesRegex(ValueError,'reader task incomplete'):
            self.review(branchesConsistent=False,issues=['The yes/no outcome is inverted.'])
        result=json.loads((self.root/'reader-review-response.json').read_text(encoding='utf-8'))
        self.assertFalse(result['branchesConsistent'])

    def test_previously_missed_inverted_date_branch_cannot_pass_a_positive_review(self):
        self.doc['blocks'][1]['text']='신청 예정일이 그보다 앞선가요? 아니라면 아직 해당 사전 신청 기간 전이므로, 시작 월을 다시 맞춰야 합니다.'
        with self.assertRaisesRegex(ValueError,'inverted'):
            self.review(evidenceQuotes=[self.doc['blocks'][1]['text']])

    def test_reviewer_cannot_claim_a_table_or_quote_absent_from_the_article(self):
        with self.assertRaisesRegex(ValueError,'reader task incomplete'):
            self.review(evidenceQuotes=['A nonexistent monthly table is present.'])

    def test_review_is_bound_to_current_document_and_negative_cache_never_retries(self):
        self.review()
        with patch('common.llm_client.generate_json',side_effect=AssertionError('Unexpected model call')):
            self.assertEqual(reader.ensure_reader_review(self.doc,self.root)['status'],'passed')
        self.doc['blocks'][1]['text']='A materially different answer must receive a new review.'
        with patch('common.llm_client.generate_json',side_effect=RuntimeError('New review required')):
            with self.assertRaisesRegex(RuntimeError,'New review'):
                reader.ensure_reader_review(self.doc,self.root)

    def test_account_money_is_never_allocated_to_posts_and_missing_is_not_zero(self):
        data=self.root/'dashboard/data/naver';data.mkdir(parents=True)
        p=datetime(2026,11,5,4,tzinfo=timezone.utc)
        (data/'public-verification.json').write_text(json.dumps({'evidence':[{'account':'soultin','title':'기초연금 신청시기 생일',
            'publicationDate':'2026-11-05','actualPublishedAt':p.isoformat(),'publicUrl':'https://blog.naver.com/example/123',
            'publicPublicationVerified':True}]}),encoding='utf-8')
        result=reader.observe_outcomes(self.root,now=p+timedelta(days=15))
        self.assertEqual(len(result['records']),1)
        windows=result['records'][0]['windows']
        self.assertEqual([w['due'] for w in windows],[True,True,False])
        self.assertTrue(all(w['attributedRevenue'] is None and w['uniqueReaders'] is None for w in windows))
        self.assertTrue(all(w['status']=='inconclusive' for w in windows))

    def test_only_exact_url_period_and_hashed_evidence_can_supply_metrics(self):
        self.test_account_money_is_never_allocated_to_posts_and_missing_is_not_zero()
        data=self.root/'dashboard/data/naver'
        p=datetime(2026,11,5,4,tzinfo=timezone.utc)
        evidence=data/'statistics-export.json';evidence.write_text('{"observed":true}',encoding='utf-8')
        sample={'url':'https://blog.naver.com/example/123','account':'soultin','scope':'post',
            'source':'owner statistics export','startAt':p.isoformat(),'endAt':(p+timedelta(days=7)).isoformat(),
            'checkedAt':(p+timedelta(days=8)).isoformat(),'evidenceFile':'dashboard/data/naver/statistics-export.json',
            'evidenceSha256':hashlib.sha256(evidence.read_bytes()).hexdigest(),
            'uniqueReaders':110,'searchVisits':90,'relatedLinkClicks':0,'attributedRevenue':500}
        evidence.write_text(json.dumps({'observations':[sample]}),encoding='utf-8')
        sample['evidenceSha256']=hashlib.sha256(evidence.read_bytes()).hexdigest()
        path=data/'content-observations.json'
        def run(value):
            path.write_text(json.dumps({'observations':[value]}),encoding='utf-8')
            return reader.observe_outcomes(self.root,now=p+timedelta(days=15))['records'][0]['windows']
        windows=run(sample)
        self.assertEqual(windows[0]['status'],'observed')
        self.assertEqual(windows[0]['relatedLinkClicks'],0)
        self.assertIsNone(windows[0]['attributedRevenue'])
        self.assertIsNone(windows[1]['uniqueReaders'])
        self.assertIsNone(run({**sample,'url':'https://blog.naver.com/example/999'})[0]['uniqueReaders'])
        self.assertIsNone(run({**sample,'endAt':(p+timedelta(days=6)).isoformat()})[0]['uniqueReaders'])
        self.assertIsNone(run({**sample,'uniqueReaders':999})[0]['uniqueReaders'])
        evidence.write_text('changed',encoding='utf-8')
        self.assertIsNone(run(sample)[0]['uniqueReaders'])


if __name__=='__main__':unittest.main()
