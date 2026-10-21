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

    def test_full_reviewer_resume_skips_prior_models_and_keeps_artifacts(self):
        import ast, asyncio, json, tempfile
        from pathlib import Path
        from unittest.mock import Mock, AsyncMock
        source=Path(r.__file__).read_text(encoding='utf-8')
        tree=ast.parse(source)
        fn=next(n for n in tree.body if isinstance(n,ast.AsyncFunctionDef) and n.name=='process_single_blog')
        start=next(i for i,n in enumerate(fn.body) if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='img_plans' for t in n.targets))
        end=next(i for i,n in enumerate(fn.body[start:],start) if isinstance(n,ast.Expr) and 'validation.json' in ast.get_source_segment(source,n))
        wrapper=ast.AsyncFunctionDef(name='run_segment',args=ast.arguments(posonlyargs=[],args=[],kwonlyargs=[],kw_defaults=[],defaults=[]),body=[ast.Global(names=["handoff","ai_result","output_dir","images_dir"])] + fn.body[start:end],decorator_list=[])
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);(folder/'images').mkdir()
            (folder/'images.md').write_text('approved image record',encoding='utf-8')
            (folder/'article.json').write_text('approved article record',encoding='utf-8')
            (folder/'assembly-edits.json').write_text('[]',encoding='utf-8')
            before={p.name:p.read_bytes() for p in folder.iterdir() if p.is_file()}
            handoff=Mock(folder=folder,data={'resume':{'fromAgent':'reviewer'}})
            handoff.file.side_effect=lambda name:folder/name
            article={'imagePlans':[],'category':'시험일정·기출팁','topicSlug':'same','title':'title','summary':'summary'}
            ns={'read_document':lambda p:{'imagePlans':[]},'handoff':handoff,'ai_result':article,
                'cached_complete':False,'layout_resume':False,'revision_post':None,'output_dir':folder,
                'images_dir':folder/'images','active_id':1,'domain':'soulnote.kr','blog_name':'blog',
                'BASE_DIR':folder.parent,'json':json,'completed_ids':[],'flow_page':None,
                'validate_images':Mock(return_value=[]),'handoff_progress':Mock(),
                'prepare_layout_evidence':AsyncMock(),'review_article':Mock(return_value={'status':'approved'}),
                'assemble_with_agent':Mock(),'review_visual_assets':Mock(),'call_model_json':Mock(),
                'current_attribution':Mock(),'ReviewRequired':r.ReviewRequired,'assemble':Mock()}
            # topicFolder requires the real output-root relationship.
            ns['BASE_DIR']=folder.parent
            output=folder.parent/'output'
            from unittest.mock import patch
            original=Path.relative_to
            with patch.object(Path,'relative_to',lambda self,other:Path('same') if other==output else original(self,other)):
                exec(compile(ast.fix_missing_locations(ast.Module(body=[wrapper],type_ignores=[])),'resume-segment','exec'),ns)
                asyncio.run(ns['run_segment']())
            ns['assemble_with_agent'].assert_not_called()
            ns['review_visual_assets'].assert_not_called()
            ns['call_model_json'].assert_not_called()
            ns['prepare_layout_evidence'].assert_awaited_once()
            ns['review_article'].assert_called_once()
            handoff.check.assert_called_once_with(complete=False)
            self.assertEqual(before,{p.name:p.read_bytes() for p in folder.iterdir() if p.is_file()})

if __name__=='__main__':unittest.main()
