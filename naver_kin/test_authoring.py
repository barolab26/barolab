import unittest
from copy import deepcopy
from unittest.mock import patch

from naver_kin import authoring


class AuthoringEvidenceTests(unittest.TestCase):
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
        entry = authoring.DEFAULT_CATALOG[0]
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


if __name__ == '__main__':
    unittest.main()
