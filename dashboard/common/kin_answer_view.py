"""Verify approved content and destination independently of visible link presentation."""
import hashlib
import re


def normalized(value):
    return ' '.join(value.replace('\xa0',' ').replace('\u200b','').split())


def approved_url(answer):
    urls=re.findall(r'https://[^\s<>"\']+',answer)
    return urls[0] if len(urls)==1 else None


def editor_cards(page):
    # Read the editor's real document; no hidden content insertion or DOM modification.
    return page.evaluate('''()=>{const editor=window.SmartEditor?.getEditor('kinpc001');
        return (editor?.getDocumentData()?.document?.components||[])
            .filter(c=>c['@ctype']==='oglink').map(c=>({link:c.link,title:c.title}))}''')


def match(answer,paragraphs,cards):
    actual='\n'.join(paragraphs)
    if normalized(actual)==normalized(answer):return 'text_link'
    url=approved_url(answer)
    if (url and normalized(actual)==normalized(answer.replace(url,'')) and len(cards)==1
            and cards[0].get('link')==url and str(cards[0].get('title') or '').strip()):
        return 'og_card'
    return None


def semantic_paragraphs(page,answer,paragraphs):
    """The frozen engine receives the same approved content/link tuple in either layout."""
    if normalized('\n'.join(paragraphs))==normalized(answer):return paragraphs
    return paragraphs+[approved_url(answer)] if match(answer,paragraphs,editor_cards(page))=='og_card' else paragraphs


def public_card_evidence(response,account,question_id,answer_id,answer,outbound_url):
    from bs4 import BeautifulSoup
    node=BeautifulSoup(response.text,'html.parser').select_one('#answer_'+str(answer_id))
    if response.status_code!=200 or node is None or approved_url(answer)!=outbound_url:return None
    paragraphs=[]
    for paragraph in node.select('.se-text-paragraph'):
        for placeholder in paragraph.select('.se-placeholder'):placeholder.decompose()
        paragraphs.append(paragraph.get_text())
    cards=[]
    for card in node.select('.se-component.se-oglink'):
        links={a.get('href') for a in card.select('a[href]')}
        title=card.select_one('.se-oglink-title')
        if links!={outbound_url} or title is None:return None
        cards.append({'link':outbound_url,'title':title.get_text(strip=True)})
    if match(answer,paragraphs,cards)!='og_card':return None
    return {'account':None,'question_id':str(question_id),'answer_id':str(answer_id),
            'public':True,'verified':False,'outbound_url':outbound_url,
            'answer_text_sha256':hashlib.sha256(answer.encode()).hexdigest(),
            'bodyVerification':'approved body without duplicate visible URL + exact OG card destination',
            'linkPresentation':'og_card','rawUrlVisible':False,'httpStatus':200,
            'reason':'Public body and exact OG destination matched; exact account ownership pending'}
