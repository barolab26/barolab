"""Regressions from public CF failures, without publishing or model calls."""
import unittest
from unittest.mock import patch
from cf_posting.posting import validate_cf_reader_content

class CFReaderGate(unittest.TestCase):
    def test_explicit_required_captures_are_not_silently_limited_to_three(self):
        from cf_posting.posting import article_image_sections
        heads=['section '+str(i) for i in range(5)]
        article={'title':'Guide','contentHtml':''.join('<h2>'+h+'</h2><p>Read the actual public rule.</p>' for h in heads),
                 'sectionImages':[{'sectionHeading':h,'image_optional':False} for h in heads]}
        sections=article_image_sections(article)
        self.assertEqual(sum(not s['image_optional'] for s in sections),5)

    def test_public_pension_notice_is_not_a_calculation_article(self):
        with self.assertRaisesRegex(ValueError, 'cannot fulfill'):
            validate_cf_reader_content({'title':'기초연금 소득인정액 모의계산', 'contentHtml':'<p>기초연금 소득인정액 산정 공식과 2026년 기준 공제 안내를 최신화했습니다.</p>'})

    def test_application_boilerplate_cannot_pass_as_an_excel_tutorial(self):
        with self.assertRaisesRegex(ValueError, 'unrelated template'):
            validate_cf_reader_content({'title':'엑셀 XLOOKUP 활용법', 'contentHtml':'<p>엑셀 수식 안내</p><ul><li>기본 자격 요건: 해당 항목별 기본 가이드라인 및 신청 자격 충족 여부 확인</li></ul>'})

    def test_editor_instructions_are_not_comparison_values(self):
        with self.assertRaisesRegex(ValueError, 'incomplete'):
            validate_cf_reader_content({'title':'여행 준비물 비교', 'contentHtml':'<table><tr><td>본문 흐름에 맞게 기재</td></tr></table>'})

    def test_caption_and_widget_title_echo_do_not_validate_wrong_subject(self):
        article={'title':'심페리카 트리오가격', 'contentHtml':'<p>'+('보험증권에서 슬개골 수술 보장과 최초 진단일, 계약일과 면책기간을 확인하세요. '*6)+'</p><figure><figcaption>심페리카 트리오가격</figcaption></figure><div data-cf-interactive-widget="v1"><p>심페리카 트리오가격</p></div>'}
        with self.assertRaisesRegex(ValueError, 'title subject'):
            validate_cf_reader_content(article)

    def test_unresolved_image_is_allowed_in_preparation_but_never_in_public_payload(self):
        article={'title':'엑셀 XLOOKUP 함수', 'contentHtml':'<p>'+('엑셀 XLOOKUP은 조건을 찾고 결과를 돌려줍니다. 예제 데이터의 이름과 날짜를 같은 형식으로 맞춘 뒤 결과를 확인하세요. '*3)+'</p><img src="{{IMAGE_0}}">'}
        validate_cf_reader_content(article)
        with self.assertRaisesRegex(ValueError, 'unresolved'):
            validate_cf_reader_content(article,published=True)

    def test_honest_limit_and_labeled_example_are_not_hidden(self):
        article={'title':'엑셀 XLOOKUP 중복 값', 'contentHtml':'<p>엑셀 XLOOKUP의 기본 검색은 첫 일치 행을 반환합니다. 가정 예시에서 이름과 날짜가 같은 두 행을 넣고 반환 결과를 비교하세요.</p><p>조회 조건은 같아도 날짜가 텍스트라면 결과가 다를 수 있습니다. 버전별 지원 여부와 원본 데이터 형식을 확인한 뒤 복사본에서 시험하세요.</p>'}
        self.assertIs(validate_cf_reader_content(article,published=True),article)

    def test_summary_formatting_preserves_authored_link_without_adding_destinations(self):
        from common.cf_tables import inject_interactive_widget
        from bs4 import BeautifulSoup
        body='<p><a href="https://support.microsoft.com/ko-kr/excel/">공식 함수 도움말</a></p><h2>오류 점검</h2><p>원본 형식과 조회 범위를 먼저 확인하세요.</p>'
        with patch('cf_posting.posting.published_inventory', side_effect=AssertionError('formatting must not browse')):
            rendered=inject_interactive_widget(body,'엑셀 오류 점검',domain='maxnote.kr')
        self.assertEqual([a['href'] for a in BeautifulSoup(rendered,'html.parser').find_all('a',href=True)],['https://support.microsoft.com/ko-kr/excel/'])

if __name__=='__main__':unittest.main()
