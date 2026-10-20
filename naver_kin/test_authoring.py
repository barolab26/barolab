import unittest
from types import SimpleNamespace
from copy import deepcopy
from unittest.mock import patch

from naver_kin import authoring


class AuthoringEvidenceTests(unittest.TestCase):
    def test_actual_old_arboretum_question_rejects_other_institution_sources(self):
        question = {'title': '아침고요수목원 예약질문',
                    'body': '내일 아침고요수목원 방문 예정입니다. 코로나 때문에 예약해야 하나요?',
                    'existing_answers': ['2021.01.01. 공식 홈페이지에 문의하세요.']}
        sources = [{'body': '구체적인 예약·입장 규칙은 국립수목원 안내에 한정됩니다.'}]
        self.assertEqual(authoring.source_fit_issue(question, sources),
                         'explicit_question_target_not_supported_by_sources')
        sources[0]['body'] += ' 아침고요수목원이라는 이름도 언급합니다.'
        self.assertEqual(authoring.source_fit_issue(question, sources),
                         'historical_time_sensitive_question_requires_original_period_evidence')

    def test_old_evergreen_same_entity_is_allowed_but_other_model_is_not(self):
        question = {'title': '국립중앙박물관 가방 보관', 'body': '물품보관함 사용 방법이 궁금합니다.',
                    'existing_answers': ['2021.01.01. 보관함을 이용하세요.']}
        self.assertIsNone(authoring.source_fit_issue(question, [{'body': '국립중앙박물관 물품보관함 사용 방법'}]))
        self.assertEqual(authoring.source_fit_issue({'title': 'WF24 모델 필터', 'body': '청소 방법'},
                         [{'body': 'WF21 모델 필터 청소'}]), 'explicit_question_target_not_supported_by_sources')

    def test_historical_policy_requires_period_evidence(self):
        question = {'title': '2021년 지원금 신청 조건', 'body': ''}
        self.assertEqual(authoring.source_fit_issue(question, [{'body': '2026년 지원금 조건'}]),
                         'question_period_not_supported_by_sources')
        self.assertIsNone(authoring.source_fit_issue(question, [{'body': '2021년 당시 지원금 신청 조건'}]))

    def test_source_quotes_alone_do_not_approve_irrelevant_or_unanswered_questions(self):
        answer = 'An exact supported sentence about another institution.'
        sources = [{'url': 'https://official.test', 'body': answer}]
        review = {key: True for key in authoring.REVIEW_FLAGS}
        review['support'] = [{'claim': answer, 'quote': answer, 'source_url': sources[0]['url']}]
        for flag in ('same_target_supported', 'time_scope_supported', 'question_resolved'):
            bad = {**review, flag: False}
            self.assertFalse(authoring._review_supported(bad, answer, sources))
            bad.pop(flag)
            self.assertFalse(authoring._review_supported(bad, answer, sources))

    def setUp(self):
        self.review = {key: True for key in authoring.REVIEW_FLAGS}
        self.review['support'] = [{'claim': 'Use the official locker.',
            'quote': 'Backpacks must be stored in the locker.', 'source_url': 'https://official.test/guide'}]
        self.sources = [{'url': 'https://official.test/guide',
                         'body': 'Rule: Backpacks must be stored in the locker. Thank you.'}]

    def test_approved_flag_without_actual_source_quote_cannot_pass(self):
        changed = deepcopy(self.review)
        changed['support'][0]['quote'] = 'All bags must be left outside.'
        self.assertFalse(authoring._review_supported(changed, 'Use the official locker.', self.sources))

    def test_claim_must_exist_in_final_answer_and_all_flags_true(self):
        self.assertTrue(authoring._review_supported(self.review, 'Use the official locker.', self.sources))
        self.assertFalse(authoring._review_supported(self.review, 'Skip the locker.', self.sources))
        changed = deepcopy(self.review); changed['adds_value'] = False
        self.assertFalse(authoring._review_supported(changed, 'Use the official locker.', self.sources))

    def test_own_article_cannot_impersonate_supplied_official_authority(self):
        changed = deepcopy(self.review); changed['support'][0]['source_url'] = 'https://www.must-good.com/x'
        self.assertFalse(authoring._review_supported(changed, 'Use the official locker.', self.sources))

    def test_explicit_slot_parsing(self):
        self.assertEqual(authoring._slot('2026-10-16_adinfo0905_0910'), '09:10')
        with self.assertRaises(ValueError):
            authoring._slot('2026-10-16_adinfo0905_2460')

    def test_relevance_uses_question_not_unrelated_existing_answer(self):
        unrelated = {'title': '세계 종교의 역사', 'body': '환웅교가 궁금합니다.',
                     'existing_answers': ['국립중앙박물관 세탁기 배수필터']}
        self.assertFalse(authoring._related_question(unrelated, authoring.DEFAULT_CATALOG))
        self.assertTrue(authoring._related_question(
            {'title': '국립중앙박물관 사진촬영 가능한가요?', 'body': '플래시 없이 가능한가요?'},
            authoring.DEFAULT_CATALOG))

    def test_specific_source_coverage_beats_generic_queue_question(self):
        entry = next(item for item in authoring.DEFAULT_CATALOG if item['domain'] == 'must-good.com')
        direct = {'title': '국립중앙박물관 관람 규정', 'body': '물품 보관함과 사진 촬영 규정이 궁금합니다.'}
        generic = {'title': '국립중앙박물관 대기', 'body': '대기 줄은 얼마나 길까요?'}
        self.assertGreater(authoring._relevance_score(direct, entry), authoring._relevance_score(generic, entry))
        self.assertEqual(authoring._relevance_score(generic, entry), 0)

    @patch('naver_kin.authoring.codex_cli.refresh_runtime')
    @patch('naver_kin.authoring.selected_model', return_value='gpt-6-luna')
    def test_unselected_model_cannot_silently_fallback(self, selected, refresh):
        with self.assertRaises(ValueError):
            authoring.generate_for_slot('adinfo0905', '2026-10-16_adinfo0905_0910', 'gpt-6.1-sol')
        refresh.assert_not_called()

    def test_dynamic_catalog_round_robin_and_general_topic_matching(self):
        custom = [
            {'url': 'https://baronote.kr/youth-rent-support-guide',
             'title': '청년월세 지원금 신청기간 자격조건 총정리',
             'keywords': ['청년월세 신청기간', '청년월세 자격조건']},
            {'url': 'https://blog.naver.com/adinfo0905/223600001',
             'title': '운전면허 갱신 적성검사 준비물 수수료 안내',
             'keywords': ['운전면허 갱신 준비물', '운전면허 적성검사 수수료']},
        ]
        q_rent = {'title': '청년월세 지원금 신청기간이 언제인가요?', 'body': '자격조건과 서류가 궁금합니다.'}
        self.assertTrue(authoring._related_question(q_rent, custom))
        self.assertGreater(authoring._relevance_score(q_rent, custom[0], used_domains_today={'baronote.kr': 0}),
                           authoring._relevance_score(q_rent, custom[0], used_domains_today={'baronote.kr': 2}))
        self.assertEqual(authoring.select_discovery_track('2026-10-17_adinfo0905_0910'), 'track_a_latest')
        self.assertEqual(authoring.select_discovery_track('2026-10-17_stone0747_0911'), 'track_b_search_top')

    def test_generation_call_keywords_match_authenticated_adapter(self):
        import ast
        import inspect
        tree = ast.parse(inspect.getsource(authoring))
        signature = inspect.signature(authoring.codex_cli.generate_local)
        for call in ast.walk(tree):
            if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute) and call.func.attr == 'generate_local':
                signature.bind('prompt', 'model', **{kw.arg: None for kw in call.keywords})

    def test_all_sixteen_cf_domains_allowed(self):
        from naver_kin import pipeline
        self.assertEqual(len(set(pipeline.CF_BASE_DOMAINS)), 16)
        for domain in pipeline.CF_BASE_DOMAINS:
            self.assertIn(domain, pipeline.HOSTS)
            self.assertIn('www.' + domain, pipeline.HOSTS)

    @patch('common.system_watchdog.save_json')
    @patch('common.system_watchdog.socket.socket')
    @patch('common.system_watchdog.is_port_open', return_value=True)
    def test_watchdog_retains_nas_monitor_contract(self, port_open, socket, save):
        from common.system_watchdog import check_and_recover_cdp_browsers
        socket.return_value.__enter__.return_value.getsockname.return_value = ('192.168.45.248', 1)
        observed = check_and_recover_cdp_browsers(auto_start=False)
        self.assertEqual(observed['host'], '192.168.45.248')
        self.assertTrue(all(observed['ports'][str(port)] for port in (9230, 9231, 9333, 9334, 9335)))
        self.assertTrue(observed['checkedAt'])

    @patch('requests.get')
    @patch('naver_kin.scheduler.subprocess.Popen')
    @patch('common.system_watchdog.is_port_open', return_value=True)
    def test_scheduler_reuses_all_five_running_browsers(self, port_open, launch, get):
        from naver_kin.scheduler import ensure_naver_browsers
        get.return_value.status_code = 200
        get.return_value.json.return_value = {'webSocketDebuggerUrl': 'ws://127.0.0.1/devtools/browser/test'}
        with patch('naver_kin.scheduler.os', SimpleNamespace(name='nt')):
            rows = ensure_naver_browsers()
        self.assertEqual({row['port'] for row in rows}, {9230, 9231, 9333, 9334, 9335})
        self.assertTrue(all(row['ready'] and not row['started'] for row in rows))
        launch.assert_not_called()

    @patch('requests.get')
    @patch('naver_kin.scheduler.subprocess.Popen')
    @patch('common.system_watchdog.is_port_open', side_effect=lambda port: port != 9230)
    def test_scheduler_starts_only_missing_account_through_batch(self, port_open, launch, get):
        from naver_kin.scheduler import ensure_naver_browsers
        get.return_value.status_code = 200
        get.return_value.json.return_value = {'webSocketDebuggerUrl': 'ws://127.0.0.1/devtools/browser/test'}
        with patch('pathlib.Path.is_file', return_value=True), patch('naver_kin.scheduler.os.name', 'nt'):
            rows = ensure_naver_browsers()
        launch.assert_called_once()
        self.assertEqual(launch.call_args.args[0][:3], ['cmd.exe', '/d', '/c'])
        self.assertTrue(launch.call_args.args[0][3].endswith('stone0747_start_cdp.bat'))
        self.assertEqual([row['port'] for row in rows if row['started']], [9230])


if __name__ == '__main__':
    unittest.main()
