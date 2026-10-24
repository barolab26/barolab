import hashlib
from types import SimpleNamespace
from unittest.mock import Mock
from common.kin_answer_view import match,semantic_paragraphs,public_card_evidence

URL='https://example.com/article?utm_source=naver_kin'
ANSWER='승인된 답변입니다.\n\n제가 운영하는 참고 글입니다.\n'+URL


def test_link_presentation_can_change_but_content_and_destination_cannot():
    body=ANSWER.replace(URL,'').splitlines()
    card={'link':URL,'title':'관련 안내'}
    assert match(ANSWER,ANSWER.splitlines(),[])=='text_link'
    assert match(ANSWER,body,[card])=='og_card'
    assert match(ANSWER,body,[]) is None
    assert match(ANSWER,body,[{**card,'link':'https://other.example/'}]) is None
    assert match(ANSWER,['변경된 답변'],[card]) is None
    page=Mock();page.evaluate.return_value=[card]
    assert match(ANSWER,semantic_paragraphs(page,ANSWER,body),[])=='text_link'


def public_html(url=URL,body='승인된 답변입니다.제가 운영하는 참고 글입니다.',answer_id='15'):
    # Keep real paragraph boundaries: flattening them would change the body.
    paragraphs=''.join('<p class="se-text-paragraph">'+line+'</p>' for line in ANSWER.replace(URL,'').splitlines())
    if body!='승인된 답변입니다.제가 운영하는 참고 글입니다.':paragraphs='<p class="se-text-paragraph">'+body+'</p>'
    return f'<div id="answer_{answer_id}">{paragraphs}<div class="se-component se-oglink"><a href="{url}"><strong class="se-oglink-title">관련 안내</strong></a></div></div>'


def test_public_card_verification_requires_exact_answer_body_and_attributed_link():
    def verify(html,status=200):return public_card_evidence(SimpleNamespace(text=html,status_code=status),'account','123','15',ANSWER,URL)
    result=verify(public_html())
    assert result['public'] and not result['verified']  # Exact account ownership is still required.
    assert result['rawUrlVisible'] is False and result['linkPresentation']=='og_card'
    assert result['answer_text_sha256']==hashlib.sha256(ANSWER.encode()).hexdigest()
    assert verify(public_html(url='https://other.example/')) is None
    assert verify(public_html(body='승인되지 않은 원고')) is None
    assert verify(public_html(answer_id='16')) is None
    assert verify(public_html(),status=403) is None
