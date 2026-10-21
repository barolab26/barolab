import unittest
from cf_posting import pipeline_runner as r
from cf_posting.domain_themes import build_final_preview_html

class CategoryPreviewTests(unittest.TestCase):
    def test_actual_category_and_body_preserved(self):
        html=build_final_preview_html('soulnote.kr','제목','<p>원래 본문</p>',article_category='시험일정·기출팁')
        soup=r.BeautifulSoup(html,'html.parser')
        self.assertEqual(soup.select_one('.meta').get_text(strip=True),'시험일정·기출팁')
        self.assertIn('원래 본문',soup.select_one('article').get_text())
        with self.assertRaises(ValueError):build_final_preview_html('soulnote.kr','제목','본문',article_category='등록안됨')
    def test_only_exact_category_failure_admitted(self):
        report={'status':'rejected','issues':['카테고리 불일치'], 'checks':{k:True for k in (*r.BLOG_REQUIRED_CHECKS,'factsSupported')}}
        report['checks']['categoryMatches']=False
        article={'category':'시험일정·기출팁'};html='<div class="meta">내일배움카드·국비</div>'
        self.assertTrue(r.category_preview_only(report,article,['시험일정·기출팁'],html))
        self.assertFalse(r.category_preview_only(report,article,[],html))
        self.assertFalse(r.category_preview_only(report,article,['시험일정·기출팁'],'<div class="meta">시험일정·기출팁</div>'))
        report['checks']['factsSupported']=False
        self.assertFalse(r.category_preview_only(report,article,['시험일정·기출팁'],html))

if __name__=='__main__':unittest.main()
