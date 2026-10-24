import tempfile
import hashlib
import types
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import Mock, patch
from PIL import Image
from common.kin_screen import publish_with_screen, visual_click


class KinScreenTests(unittest.TestCase):
    def test_retry_after_pre_submit_failure_preserves_prior_screen_evidence(self):
        page=Mock();page.screenshot.side_effect=lambda path,**kw:Image.new('RGB',(960,960)).save(path)
        @contextmanager
        def session(account):yield page
        engine=types.SimpleNamespace(_naver_browser_session=session,_naver_browser__type_paragraphs=Mock(),_naver_browser_ACCOUNTS={'test':65001})
        gate=Mock();answer='same approved draft'
        def original(account,url,text,before):
            with engine._naver_browser_session(account) as visible:
                visible.locator('._answerWriteButton').first.click()
        with tempfile.TemporaryDirectory() as temp,patch('common.ubuntu_naver_browser.focus_workflow_window'),patch('common.llm_client.generate_json',return_value={'kind':'stop'}):
            root=Path(temp)/'ego-kin'/hashlib.sha256(answer.encode()).hexdigest()[:16]
            old=root/'click-00';old.mkdir(parents=True);(old/'proof.json').write_text('original proof')
            for _ in range(2):
                with self.assertRaisesRegex(RuntimeError,'could not identify'):
                    publish_with_screen(engine,original,'test','https://kin.naver.com/question',answer,gate,temp)
            attempts=list(root.glob('*/click-00/before-0.png'))
            self.assertEqual(len(attempts),2)
            self.assertEqual((old/'proof.json').read_text(),'original proof')
            self.assertIs(engine._naver_browser_session,session)
        gate.assert_not_called();page.mouse.click.assert_not_called()

    def test_visible_typing_preserves_blank_paragraphs_callback_and_pending_tab(self):
        page=Mock();page.paragraphs=[];page.locator.return_value.all_inner_texts.side_effect=lambda:page.paragraphs
        @contextmanager
        def session(account):yield page
        typer=Mock();engine=types.SimpleNamespace(_naver_browser_session=session,_naver_browser__type_paragraphs=typer,_naver_browser_ACCOUNTS={'test':9231})
        answer='핵심 답변입니다.\n\n확인 방법입니다.\n\n제가 운영하는 글입니다.\nhttps://www.example.com/guide\n'
        submitted=[]
        def click(real,target,port,folder,description,before_click=None):
            if before_click:
                self.assertEqual(submitted,[])
                before_click()
            if '등록' in description:self.assertEqual(submitted,['durable-gate'])
        def run(real,**kwargs):
            Path(kwargs['folder']).mkdir(parents=True,exist_ok=True)
            self.assertEqual(kwargs['input_check']([]),'')
            written=[];lines=[]
            for reference in kwargs['references']:
                written.append(reference['ref']);lines.append(reference['text']);page.paragraphs=lines+['']
                self.assertEqual(kwargs['input_check'](written),'')
            kwargs['completion_check']()
            page.paragraphs=[line for line in lines if line]
            with self.assertRaises(ValueError):kwargs['completion_check']()
            page.paragraphs=lines+[''];return {'turns':[{}]}
        def original(account,url,text,before):
            with engine._naver_browser_session(account) as visible:
                self.assertEqual(visible,page)
                visible.locator('._answerWriteButton').first.click()
                visible.locator('.se-canvas .se-text-paragraph').first.click()
                engine._naver_browser__type_paragraphs(visible.keyboard,text)
                before();visible._barolab_kin_submission_pending=True
                visible.locator('#answerRegisterButton').click(timeout=12000)
                return {'state':'submitted_unknown'}
        with tempfile.TemporaryDirectory() as folder,patch('common.kin_screen.visual_click',side_effect=click) as clicks,patch('common.ego_screen.run',side_effect=run):
            result=publish_with_screen(engine,original,'test','https://kin.naver.com/question',answer,lambda:submitted.append('durable-gate'),folder)
        self.assertEqual(result['state'],'submitted_unknown');self.assertEqual(clicks.call_count,3)
        self.assertIs(engine._naver_browser_session,session);self.assertIs(engine._naver_browser__type_paragraphs,typer)
        self.assertTrue(page._barolab_kin_submission_pending)

    def test_visual_click_is_one_attempt_and_rejects_coordinates_outside_approved_button(self):
        for x,expected in [(150,True),(5,False)]:
            with self.subTest(x=x),tempfile.TemporaryDirectory() as temp:
                page=Mock();page.screenshot.side_effect=lambda path,**kw:Image.new('RGB',(960,960)).save(path)
                target=Mock();target.evaluate.return_value=True;target.is_enabled.return_value=True;target.bounding_box.return_value={'x':100,'y':100,'width':100,'height':100}
                folder=Path(temp)/'click'
                def physical_click(*args):self.assertTrue((folder/'click-attempt.json').exists())
                page.mouse.click.side_effect=physical_click
                plan={'kind':'click','x':x,'y':150,'direction':'','reason':'화면에서 확인한 버튼'}
                with patch('common.ubuntu_naver_browser.focus_workflow_window'),patch('common.llm_client.generate_json',return_value=plan):
                    if expected:visual_click(page,target,65001,folder,'등록 버튼')
                    else:
                        with self.assertRaises(TimeoutError):visual_click(page,target,65001,folder,'등록 버튼')
                self.assertEqual(page.mouse.click.call_count,1 if expected else 0)
                if expected:
                    gate=Mock(side_effect=ValueError('durable gate rejected'))
                    with patch('common.ubuntu_naver_browser.focus_workflow_window'),patch('common.llm_client.generate_json',return_value=plan):
                        with self.assertRaisesRegex(ValueError,'durable gate rejected'):
                            visual_click(page,target,65001,Path(temp)/'rejected-gate','등록 버튼',before_click=gate)
                    self.assertEqual(page.mouse.click.call_count,1)
                    gate.assert_called_once()

    def test_layout_shift_reobserves_before_one_durable_submit(self):
        page=Mock();page.screenshot.side_effect=lambda path,**kw:Image.new('RGB',(960,960)).save(path)
        target=Mock();target.evaluate.return_value=True;target.is_enabled.return_value=True
        target.bounding_box.side_effect=[{'x':300,'y':300,'width':50,'height':50},{'x':100,'y':100,'width':100,'height':100}]
        plan={'kind':'click','x':150,'y':150,'direction':'','reason':'새 화면에서 버튼 확인'};gate=Mock()
        with tempfile.TemporaryDirectory() as temp,patch('common.ubuntu_naver_browser.focus_workflow_window'),patch('common.llm_client.generate_json',return_value=plan) as model:
            folder=Path(temp)/'submit';visual_click(page,target,65001,folder,'Post 버튼',before_click=gate)
            self.assertTrue((folder/'rejected-0.json').exists())
        self.assertEqual(model.call_count,2);gate.assert_called_once();page.mouse.click.assert_called_once_with(150,150)

    def test_visual_failure_before_physical_submit_does_not_commit_the_durable_gate(self):
        page=Mock()
        @contextmanager
        def session(account):yield page
        typer=Mock();engine=types.SimpleNamespace(_naver_browser_session=session,_naver_browser__type_paragraphs=typer,_naver_browser_ACCOUNTS={'test':65001})
        gate=Mock()
        def original(account,url,answer,before):
            with engine._naver_browser_session(account) as visible:
                before()
                visible.locator('#answerRegisterButton').click()
        with tempfile.TemporaryDirectory() as folder,patch('common.kin_screen.visual_click',side_effect=TimeoutError('visual decision timeout')):
            with self.assertRaises(TimeoutError):publish_with_screen(engine,original,'test','https://kin.naver.com/question','approved text',gate,folder)
        gate.assert_not_called()
        self.assertIs(engine._naver_browser_session,session)
        self.assertIs(engine._naver_browser__type_paragraphs,typer)
