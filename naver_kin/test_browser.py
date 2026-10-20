"""Evidence gates are offline: never submit an answer during a test."""
import unittest
import json
import os
from types import SimpleNamespace
from unittest.mock import patch, Mock
from contextlib import contextmanager

from naver_kin import browser
from common import browser_session


class BrowserEvidenceTests(unittest.TestCase):
    def ownership_html(self, account='stone0747', total=2, loaded=2, own=None, logged_in=True):
        cards = ''.join('<div id="answer_'+str(n)+'" class="answerArea'+(' _myAnswer' if n==own else '')+'">'
                        + ('<a id="optModify'+str(n)+'">수정</a><a id="optDelete'+str(n)+'">삭제</a>' if n==own else '')
                        + '</div>' for n in range(1,loaded+1))
        return ('<script>naver.isLogin = '+str(logged_in).lower()+'; var params={loginUserId: "'+account+'"};'
                'window.oElementBaLogSender = new naver.kin.pc.detail.ElementBaLogSender({'
                'dirId: 901, docId: 486320125, totalAnswerCount: '+str(total)+', referer: null});</script>'
                '<div class="endTitleSection">Question</div><div class="questionDetail">Body</div>'
                '<span class="_answerCount">'+str(total)+'</span>'+cards)

    def test_current_question_complete_absence_does_not_scan_account_history(self):
        result = browser._parse_question_ownership(self.ownership_html(), 'stone0747', '486320125')
        self.assertTrue(result['known'])
        self.assertTrue(result['complete'])
        self.assertEqual(result['answer_ids'], [])

    def test_partial_question_cannot_prove_absence(self):
        result = browser._parse_question_ownership(self.ownership_html(total=100,loaded=5), 'stone0747', '486320125')
        self.assertFalse(result['known'])
        self.assertFalse(result['complete'])

    def test_partial_page_proves_positive_ownership_but_not_absence(self):
        result = browser._parse_question_ownership(self.ownership_html(total=100, loaded=5, own=2), 'stone0747', '486320125')
        self.assertFalse(result['known'])
        self.assertFalse(result['complete'])
        self.assertEqual(result['verified_owned_answer_ids'], ['2'])
        mismatch = self.ownership_html(total=100, loaded=5, own=2).replace(' _myAnswer', '')
        self.assertFalse(browser._parse_question_ownership(mismatch, 'stone0747', '486320125').get('verified_owned_answer_ids'))

    def test_existing_own_answer_matches_exact_account_and_number(self):
        result = browser._parse_question_ownership(self.ownership_html(own=2), 'stone0747', '486320125')
        self.assertTrue(result['known'])
        self.assertEqual(result['answer_ids'], ['2'])
        with self.assertRaises(browser.LoginRequiredError):
            browser._parse_question_ownership(self.ownership_html(account='adinfo0905'), 'stone0747', '486320125')
        with self.assertRaises(browser.LoginRequiredError):
            browser._parse_question_ownership(self.ownership_html(logged_in=False), 'stone0747', '486320125')

    def test_missing_total_and_disagreeing_owner_markers_stay_unknown(self):
        missing = self.ownership_html().replace('totalAnswerCount: 2,', '')
        self.assertFalse(browser._parse_question_ownership(missing,'stone0747','486320125')['known'])
        mismatch = self.ownership_html(own=2).replace(' _myAnswer','')
        self.assertFalse(browser._parse_question_ownership(mismatch,'stone0747','486320125')['known'])

    def test_only_authorized_accounts(self):
        self.assertEqual(browser.account_config('adinfo0905')['cdp_port'], 9231)
        self.assertEqual(browser.account_config('stone0747')['cdp_port'], 9230)
        with self.assertRaises(ValueError):
            browser.account_config('soultin')

    def test_question_url_gate(self):
        self.assertEqual(browser.question_id('https://kin.naver.com/qna/detail.naver?docId=123'), '123')
        for url in ('https://example.org/qna/detail.naver?docId=123',
                    'https://kin.naver.com.evil.test/qna/detail.naver?docId=123',
                    'https://x@kin.naver.com/qna/detail.naver?docId=123',
                    'https://kin.naver.com:443/qna/detail.naver?docId=123',
                    'https://kin.naver.com/qna/detail.naver?docId=123&docId=456',
                    'https://kin.naver.com/qna/detail.naver?docId=123#other',
                    'https://kin.naver.com/qna/detail.naver?docId=x'):
            with self.assertRaises(ValueError):
                browser.question_id(url)

    def test_visible_register_button_after_submission_is_never_clicked_twice(self):
        page = Mock()
        nodes = Mock(); nodes.all_inner_texts.return_value = []
        paragraphs = Mock(); paragraphs.all_inner_texts.return_value = ['reviewed answer']
        button = Mock(); button.count.return_value = 1; button.is_enabled.return_value = True
        button.is_visible.return_value = True
        def locate(selector):
            if selector == '#answerRegisterButton': return button
            if selector == '.se-canvas .se-text-paragraph .__se-node': return nodes
            if selector == '.se-canvas .se-text-paragraph': return paragraphs
            return Mock()
        page.locator.side_effect = locate
        page.content.return_value = '<html>Submission result is not yet observable</html>'
        dialog=Mock();dialog.type='confirm';dialog.message='Wait for processing user@example.com\nAuthorization: Bearer privateBearer\npassword="private quoted value"'
        button.click.side_effect=lambda **kwargs: next(call.args[1] for call in page.on.call_args_list if call.args[0]=='dialog')(dialog)
        @contextmanager
        def session(_): yield page
        before = Mock()
        with patch.object(browser, 'session', session), patch.object(browser, '_question_ownership', return_value={
                'answer_ids': [], 'known': True, 'complete': True}), patch.object(browser, '_read'), \
                patch.object(browser, '_check_service_state'), patch.object(browser, '_type_paragraphs'):
            result = browser.publish('adinfo0905', 'https://kin.naver.com/qna/detail.naver?docId=123',
                                     'reviewed answer', before_submit=before)
        before.assert_called_once()
        button.click.assert_called_once_with(timeout=12000)
        self.assertIsNone(result['answer_id'])
        self.assertIn('submitted_unverified', result['reason'])
        dialog.dismiss.assert_called_once();dialog.accept.assert_not_called()
        self.assertEqual(result['submissionObservation']['dialogs'][0]['type'],'confirm')
        self.assertNotIn('private',json.dumps(result))
        self.assertNotIn('user@example.com',json.dumps(result))

    def test_delayed_exact_owned_answer_is_observed_without_another_click(self):
        page=Mock(); button=Mock(); button.count.return_value=1;button.is_enabled.return_value=True
        nodes=Mock();nodes.all_inner_texts.return_value=[]
        paragraphs=Mock();paragraphs.all_inner_texts.return_value=['reviewed answer']
        page.locator.side_effect=lambda selector: button if selector=='#answerRegisterButton' else nodes if selector=='.se-canvas .se-text-paragraph .__se-node' else paragraphs if selector=='.se-canvas .se-text-paragraph' else Mock()
        page.content.side_effect=['<html>pending</html>', '<div class="answerArea _myAnswer" id="answer_123">reviewed answer</div>']
        response=SimpleNamespace(url='https://kin.naver.com/ajax/detail/registerAnswerForSmartEditorOne.naver?token=private',status=200,
            request=SimpleNamespace(method='POST',frame=SimpleNamespace(page=page),post_data='docId=123&token=private'), headers={'content-type':'application/json; charset=utf-8'},
            json=lambda:{'isSuccess':True,'token':'private','message':'private'})
        button.click.side_effect=lambda **kwargs: next(call.args[1] for call in page.on.call_args_list if call.args[0]=='response')(response)
        @contextmanager
        def session(_): yield page
        with patch.object(browser,'session',session), patch.object(browser,'_read'), \
                patch.object(browser,'_question_ownership',return_value={'known':True,'complete':True,'answer_ids':[]}), \
                patch.object(browser,'_parse_question_ownership',side_effect=[{'verified_owned_answer_ids':[]},{'verified_owned_answer_ids':['123']}]), \
                patch.object(browser,'_check_service_state'), patch.object(browser,'_type_paragraphs'):
            result=browser.publish('adinfo0905','https://kin.naver.com/qna/detail.naver?docId=123','reviewed answer',Mock())
        self.assertEqual(result['answer_id'],'123')
        button.click.assert_called_once()
        self.assertEqual(page.remove_listener.call_count,2)
        self.assertEqual(result['submissionObservation']['responses'],[{'path':'/ajax/detail/registerAnswerForSmartEditorOne.naver','status':200,'questionBound':True,'contentType':'application/json','resultCodes':{'isSuccess':True}}])
        self.assertNotIn('private',json.dumps(result))

    def test_response_candidate_requires_single_exact_question_and_stays_unverified(self):
        for doc_id, count, expected in (('123',1,'456'),('999',1,None),('123',2,None),
                                         ('malformed',1,None),('non_json',1,None),('unbound',1,None)):
            with self.subTest(doc_id=doc_id,count=count):
                page=Mock();button=Mock();button.count.return_value=1;button.is_enabled.return_value=True
                nodes=Mock();nodes.all_inner_texts.return_value=[]
                paragraphs=Mock();paragraphs.all_inner_texts.return_value=['reviewed answer']
                page.locator.side_effect=lambda selector: button if selector=='#answerRegisterButton' else nodes if selector=='.se-canvas .se-text-paragraph .__se-node' else paragraphs if selector=='.se-canvas .se-text-paragraph' else Mock()
                page.content.return_value='<html>old DOM without the new answer</html>'
                response=SimpleNamespace(url='https://kin.naver.com/ajax/detail/registerAnswerForSmartEditorOne.naver',
                    status=200,headers={'content-type':'application/json'},
                    request=SimpleNamespace(method='POST',frame=SimpleNamespace(page=page),post_data='docId='+doc_id+'&token=private'),
                    json=lambda:{'isSuccess':True,'result':{'result':{'answerNo':456}}})
                if doc_id == 'malformed':
                    response.json=lambda:{'isSuccess':True,'result':'unexpected string'}
                elif doc_id == 'non_json':
                    response.json=Mock(side_effect=ValueError('private malformed body'))
                elif doc_id == 'unbound':
                    response.request=SimpleNamespace(method='POST')
                def clicked(**kwargs):
                    observer=next(call.args[1] for call in page.on.call_args_list if call.args[0]=='response')
                    for _ in range(count):observer(response)
                button.click.side_effect=clicked
                @contextmanager
                def session(_):yield page
                with patch.object(browser,'session',session),patch.object(browser,'_read'), \
                        patch.object(browser,'_question_ownership',return_value={'known':True,'complete':True,'answer_ids':[]}), \
                        patch.object(browser,'_parse_question_ownership',return_value={'verified_owned_answer_ids':[]}), \
                        patch.object(browser,'_check_service_state'),patch.object(browser,'_type_paragraphs'):
                    result=browser.publish('adinfo0905','https://kin.naver.com/qna/detail.naver?docId=123','reviewed answer',Mock())
                self.assertEqual(result['answer_id'],expected)
                self.assertEqual(len(result['submissionObservation']['responses']),count)
                self.assertEqual(result['submissionObservation']['responses'][0]['status'],200)
                if doc_id == 'unbound':
                    self.assertFalse(result['submissionObservation']['responses'][0]['questionBound'])
                self.assertNotIn('private',json.dumps(result))
                self.assertIn('submitted_unverified',result['reason'])
                button.click.assert_called_once()
                if expected:
                    self.assertTrue(result['submissionObservation']['responseCandidateOnly'])
                    self.assertFalse(result['submissionObservation']['exactOwnedBodyMatched'])
                    self.assertNotIn('verified',result)

    def test_session_closes_only_owned_safe_tabs(self):
        from unittest.mock import MagicMock
        for reused, pending, draft in ((False,False,False),(True,False,False),(False,True,False),(False,False,True)):
            with self.subTest(reused=reused,pending=pending,draft=draft):
                page=Mock();page.url='https://kin.naver.com/';page._barolab_kin_submission_pending=False
                page.has_draft=False
                identity=Mock();identity.count.return_value=1;identity.inner_text.return_value='adinfo0905'
                page.locator.return_value=identity
                context=SimpleNamespace(pages=[page] if reused else [],new_page=Mock(return_value=page))
                @contextmanager
                def awake(*args):yield SimpleNamespace(contexts=[context])
                @contextmanager
                def locked(*args):yield
                with patch('playwright.sync_api.sync_playwright',return_value=MagicMock()), \
                        patch.object(browser,'awake_browser',awake),patch.object(browser,'account_lock',locked), \
                        patch.object(browser,'_check_account_blog_not_busy'),patch.object(browser,'_check_service_state'), \
                        patch.object(browser,'_has_editor_draft',side_effect=lambda current:current.has_draft):
                    with browser.session('adinfo0905') as selected:
                        self.assertIs(selected,page)
                        selected._barolab_kin_submission_pending=pending
                        selected.has_draft=draft
                self.assertEqual(page.close.call_count,int(not reused and not pending and not draft))

    def test_unreadable_editor_is_preserved(self):
        page=Mock();page.locator.side_effect=RuntimeError('unavailable document')
        self.assertTrue(browser._has_editor_draft(page))
        with self.assertRaisesRegex(RuntimeError,'Existing KnowledgeIn editor draft'):
            browser.preserve_editor(page)

    def test_partial_ownership_cannot_authorize_submission_from_recent_history(self):
        page=Mock()
        @contextmanager
        def session(_): yield page
        with patch.object(browser,'session',session), patch.object(browser,'_question_ownership',return_value={
                'known':False,'complete':False,'answer_ids':[],'reason':'question_answers_partially_loaded'}), \
                patch.object(browser,'_own_answer_map') as recent:
            with self.assertRaisesRegex(RuntimeError,'incomplete'):
                browser.publish('adinfo0905','https://kin.naver.com/qna/detail.naver?docId=123','answer',Mock())
        recent.assert_not_called();page.locator.assert_not_called()

    def test_publish_requires_durable_callback_before_browser(self):
        with self.assertRaises(ValueError):
            browser.publish('adinfo0905', 'https://kin.naver.com/qna/detail.naver?docId=123', 'answer')

    @patch('naver_kin.browser.session', side_effect=RuntimeError('offline no ownership'))
    @patch('naver_kin.browser.requests.get')
    def test_public_body_link_does_not_prove_masked_author(self, get, session):
        get.return_value = Mock(status_code=200, text='''<div id="answer_1">
          <div class="profile_card"><a href="/profile/index.naver?u=opaque">adin****</a></div>
          <p>Reviewed answer</p><a href="https://www.must-good.com/x?utm_source=naver_kin">link</a></div>''')
        evidence = browser.verify_public('adinfo0905', 'https://kin.naver.com/qna/detail.naver?docId=123',
                                         'Reviewed answer', 'https://www.must-good.com/x?utm_source=naver_kin', '1')
        self.assertTrue(evidence['public'])
        self.assertFalse(evidence['verified'])
        self.assertIsNone(evidence['account'])

    def test_exact_answer_url_replaces_stale_pagination(self):
        from urllib.parse import parse_qs, urlsplit
        url = browser.exact_answer_url('https://kin.naver.com/qna/detail.naver?dirId=601&docId=123&answerNo=27#answer31', '31')
        self.assertEqual(parse_qs(urlsplit(url).query)['answerNo'], ['31'])
        self.assertEqual(parse_qs(urlsplit(url).query)['docId'], ['123'])
        self.assertEqual(urlsplit(url).fragment, 'answer31')

    @patch('naver_kin.browser.requests.get')
    def test_verify_requests_exact_answer_page(self, get):
        get.return_value = Mock(status_code=200, text='<div id="answer_31"><div class="profile_card"><a href="/profile?userId=adinfo0905">owner</a></div><p>Reviewed answer</p><a href="https://www.must-good.com/x">link</a></div>')
        result = browser.verify_public('adinfo0905', 'https://kin.naver.com/qna/detail.naver?docId=123&answerNo=27#answer31', 'Reviewed answer', 'https://www.must-good.com/x', '31')
        self.assertTrue(result['verified'])
        self.assertIn('answerNo=31', get.call_args.args[0])
        self.assertEqual(result['answer_url'], get.call_args.args[0])

    def test_existing_editor_draft_preserved(self):
        page = Mock()
        page.locator.return_value.all_inner_texts.return_value = ['User draft']
        with self.assertRaises(RuntimeError):
            browser.preserve_editor(page)
        page.goto.assert_not_called()

    def test_smart_editor_newlines_use_real_enter(self):
        keyboard = Mock()
        browser._type_paragraphs(keyboard, 'First\n\nSecond\nhttps://www.must-good.com/x')
        self.assertEqual(keyboard.insert_text.call_args_list,
                         [unittest.mock.call('First'), unittest.mock.call('Second'),
                          unittest.mock.call('https://www.must-good.com/x')])
        self.assertEqual(keyboard.press.call_count, 4)
        for call in keyboard.insert_text.call_args_list:
            self.assertNotIn('\n', call.args[0])

    @patch('naver_kin.browser.websocket.create_connection')
    @patch('naver_kin.browser.requests.get')
    @patch('naver_kin.browser.preflight')
    def test_suspended_tab_debugger_stays_attached_until_session_exits(self, preflight, get, connect):
        preflight.return_value = {'webSocketDebuggerUrl': 'ws://127.0.0.1:9230/devtools/browser/known'}
        get.return_value.json.return_value = [{'type': 'page', 'id': 'known',
            'webSocketDebuggerUrl': 'ws://127.0.0.1:9230/devtools/page/known'}]
        connection = connect.return_value
        connection.recv.return_value = '{"id":1,"result":{}}'
        playwright = Mock()
        with browser.awake_browser(playwright, browser.account_config('stone0747')):
            connection.close.assert_not_called()
            self.assertEqual(preflight.call_args.kwargs['process_timeout'], 30)
            playwright.chromium.connect_over_cdp.assert_called_once_with(
                'ws://127.0.0.1:9230/devtools/browser/known', timeout=20000, no_defaults=True)
        connection.close.assert_called_once()

    @patch('common.browser_session.subprocess.run')
    @patch('common.browser_session.os', SimpleNamespace(name='nt', environ=os.environ, path=os.path))
    def test_process_validation_uses_default_thirty_and_accepts_explicit_timeout(self, run):
        expected = {'ProcessId': 123, 'ExecutablePath': 'C:/expected/chrome.exe',
                    'ProfilePath': 'C:/expected/User Data'}
        run.return_value = Mock(returncode=0, stdout=json.dumps(expected))
        browser_session._runtime(9230, expected['ExecutablePath'], expected['ProfilePath'])
        self.assertEqual(run.call_args.kwargs['timeout'], 30)
        self.assertIn('-LocalPort 9230', run.call_args.args[0][-1])
        browser_session._runtime(9230, expected['ExecutablePath'], expected['ProfilePath'], process_timeout=15)
        self.assertEqual(run.call_args.kwargs['timeout'], 15)
        for rows in ({**expected, 'ExecutablePath': 'C:/other/chrome.exe'},
                     {**expected, 'ProfilePath': 'C:/other/User Data'}, [expected, expected]):
            run.return_value = Mock(returncode=0, stdout=json.dumps(rows))
            with self.assertRaises(RuntimeError):
                browser_session._runtime(9230, expected['ExecutablePath'], expected['ProfilePath'], process_timeout=30)

    def test_own_answer_map_bounds_to_three_pages_without_crashing_above_twenty(self):
        page = Mock()
        def fake_get(url, timeout=15000):
            page_links = ''.join(f'<a href="/myinfo/answerList.naver?page={p}">{p}</a>' for p in range(1, 28))
            html = f'<a href="/qna/mydetail.naver?docId=1001&answerNo=1">a</a>{page_links}'
            resp = Mock(status=200, url='https://kin.naver.com/myinfo/answerList.naver')
            resp.text.return_value = html
            return resp
        page.context.request.get.side_effect = fake_get
        result = browser._own_answer_map(page)
        self.assertEqual(result, {'1001': {'1'}})
        self.assertEqual(page.context.request.get.call_count, 3)

    @patch('common.browser_session._runtime', side_effect=RuntimeError('stop before CDP network'))
    def test_preflight_forwards_process_timeout_without_bypassing_validation(self, runtime):
        for configured in (None, 30):
            kwargs = {} if configured is None else {'process_timeout': configured}
            with self.assertRaisesRegex(RuntimeError, 'stop before CDP network'):
                browser_session.preflight('http://127.0.0.1:9230', 'C:/expected/chrome.exe',
                                          'C:/expected/User Data', **kwargs)
            self.assertEqual(runtime.call_args.kwargs['process_timeout'], configured or 30)

    def test_question_specific_layer_does_not_halt_account(self):
        page, layer = Mock(), Mock()
        page.url = 'https://kin.naver.com/qna/detail.naver?docId=12345'
        layer.is_visible.return_value = True
        layer.inner_text.return_value = '현재 활동이 보류된 상태입니다. 해당 분야에서 답변 작성이 불가합니다.'
        page.locator.return_value.all.return_value = [layer]
        with self.assertRaises(browser.QuestionUnavailableError):
            browser._check_service_state(page)

    def test_explicit_account_protection_halts(self):
        page, layer = Mock(), Mock()
        page.url = 'https://kin.naver.com/qna/detail.naver?docId=12345'
        layer.is_visible.return_value = True
        layer.inner_text.return_value = '아이디 보호조치 해제를 위해 보안문자를 확인해 주세요.'
        page.locator.return_value.all.return_value = [layer]
        with self.assertRaises(browser.AccountProtectionError):
            browser._check_service_state(page)

    @patch('naver_kin.browser._read')
    @patch('naver_kin.browser.session')
    def test_closed_question_skips_without_interrupting_discovery(self, session, read):
        page = Mock()
        page.locator.return_value.evaluate_all.return_value = [
            'https://kin.naver.com/qna/detail.naver?docId=12345',
            'https://kin.naver.com/qna/detail.naver?docId=23456']
        @contextmanager
        def opened(account):
            yield page
        session.side_effect = opened
        read.side_effect = [browser.QuestionUnavailableError('closed'), {'question_id': '23456'}]
        result = browser.discover('adinfo0905', ['museum'], limit=2)
        self.assertEqual(result, [{'question_id': '23456'}])
        self.assertEqual(result.skipped[0]['reason'], 'question_unavailable')

    @patch('naver_kin.browser.requests.get')
    def test_exact_utm_url_required(self, get):
        get.return_value = Mock(status_code=200, text='''<div id="answer_1"><p>Reviewed answer</p>
           <a href="https://www.must-good.com/x">link</a></div>''')
        evidence = browser.verify_public('adinfo0905', 'https://kin.naver.com/qna/detail.naver?docId=123',
                                         'Reviewed answer', 'https://www.must-good.com/x?utm_source=naver_kin', '1')
        self.assertFalse(evidence['verified'])
        self.assertFalse(evidence['public'])

    @patch('naver_kin.browser.requests.get')
    def test_wrong_answer_id_cannot_verify(self, get):
        get.return_value = Mock(status_code=200, text='<div id="answer_2">Reviewed answer</div>')
        evidence = browser.verify_public('adinfo0905', 'https://kin.naver.com/qna/detail.naver?docId=123',
                                         'Reviewed answer', 'https://www.must-good.com/x', '1')
        self.assertFalse(evidence['verified'])


if __name__ == '__main__':
    unittest.main()
