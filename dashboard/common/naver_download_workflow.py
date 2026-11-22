"""B-only reconstruction of the observed MoneyHomepan search workflow.

Extracted programs are evidence, never imported or executed. Common host factual,
submission, ownership and receipt safeguards remain independent of this workflow.
"""
import ast
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
from io import BytesIO
import ipaddress
import json
from pathlib import Path
import re
import socket
import time
from urllib.parse import quote, urljoin, urlsplit

import requests
from PIL import Image
from bs4 import BeautifulSoup
from common.collection_observability import load, write
from common.source_discovery import public_https_url

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT/'dashboard/data/repair-workflows/moneyhomepan-20261106/analysis-readable'
PROTOCOL = 'moneyhomepan-search-download-v2'
IMPLEMENTATION_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
DEVIATIONS = [
    'Company model/account transport replaces original Models.run and Claude vision transport.',
    'Company factual, ownership, credential, submission and receipt safeguards remain enabled.',
    'Polish failure holds instead of returning an unreviewed draft.',
    'No band crop: original source marks and all original pixels are preserved.',
    'Public HTTPS downloads are bounded; inaccessible sources are not bypassed.',
]
GRAPHIC = re.compile(r'카드뉴스|인포그래픽|통계표|차트|그래프|도표|일정표|광고배너|로고|infographic|chart|graph|banner|logo', re.I)
EVENT = re.compile(r'포토\]|화보|제작발표회|시사회|레드카펫|쇼케이스|팬미팅|팬사인회|포토월|포즈|미모|비주얼|출국|입국|공항패션')
UI = re.compile(r'logo|icon|sprite|banner|btn_|btn-|button|favicon|profile|thumb_s|blank|spacer|footer|header|reporter|ico_|shop|store|adcr|gfmarket', re.I)
_search_at = 0.0
_search_cache = {}


def digest(value):
    data = value if isinstance(value, bytes) else json.dumps(value, ensure_ascii=False, sort_keys=True).encode()
    return hashlib.sha256(data).hexdigest()


def literal(text, prefix):
    """Read one static JS string literal as inert data, never eval JS."""
    tail = text[text.index(prefix)+len(prefix):].lstrip()
    match = re.match(r'''("(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')''', tail)
    if not match:
        raise ValueError('Original static prompt literal unavailable: '+prefix)
    return ast.literal_eval(match.group())


def source_instructions():
    writer = (SOURCE/'services/plugin-writer.js').read_text(encoding='utf-8')
    vision = (SOURCE/'services/vision.js').read_text(encoding='utf-8')
    contract = literal(writer, 'const contract =')
    # The vision template is read as text; its only interpolation is supplied below.
    start = vision.index('return `Inspect the actual pixels')+len('return `')
    end = vision.index('${JSON.stringify(e)}.', start)
    rules = (SOURCE/'services/prompts/naver_geo_plugin.txt').read_text(encoding='utf-8')
    return rules, contract, vision[start:end]


def original_search_rules():
    writer=(SOURCE/'services/plugin-writer.js').read_text(encoding='utf-8')
    body=writer[writer.index('function writingRules('):writer.index('function imageRules(')]
    start=body.index('a = [`')+len('a = [`');end=body.index('`];',start)
    length=body[start:end].replace('${i}','1600').replace('${o}','1900').replace('${s}','1750')
    strings=[]
    for match in re.finditer(r'a\.push\(',body):
        try:strings.append(literal(body[match.start():],'a.push('))
        except ValueError:continue
    # Default search mode, left alignment, no tone override or additional request.
    text_rules=[s for s in strings if s.startswith(('작성 과정 숨기기','블로그 글처럼 쓰기','검색형 서두'))]
    section=writer[writer.index('function imageRules('):writer.index('const SOURCE_FOR_AI')]
    start=section.index('return `')+len('return `');end=section.index('`;',start)
    image_rules=section[start:end]
    pattern=r'\$\{"home" === t \? ("(?:\\.|[^"\\])*") : ("(?:\\.|[^"\\])*")\}'
    image_rules=re.sub(pattern,lambda m:ast.literal_eval(m.group(2)),image_rules)
    if '${' in image_rules:raise ValueError('Original image rule template changed')
    return length+'\n'+'\n'.join(text_rules)+'\n'+image_rules


def protocol_evidence():
    files = ['services/plugin-writer.js', 'services/images.js', 'services/vision.js',
             'services/facts.js', 'public/image-slots.js', 'services/prompts/naver_geo_plugin.txt']
    return {'protocol': PROTOCOL, 'implementationSha256':IMPLEMENTATION_SHA256,
            'sourceFiles': [{'path': str(SOURCE/f),
            'sha256': digest((SOURCE/f).read_bytes())} for f in files],
            'deviations': DEVIATIONS, 'exactOriginalReproduction': False,
            'sequence': ['research', 'original-search-instructions', 'draft', 'same-model-polish',
                         'conditional-length-adjustment', 'mobile-paragraphs', 'original-image-slots',
                         'news-photo-search', 'download', 'pixel-review', 'deduplicate',
                         'slot-placement', 'host-final-review', 'host-editor-submit', 'host-receipt-verification']}


def fetch_public(url, *, image=False):
    """Credential-free bounded public fetch; validate each redirect and destination."""
    for _ in range(4):
        url = public_https_url(url)
        addresses = socket.getaddrinfo(urlsplit(url).hostname, 443, type=socket.SOCK_STREAM)
        if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
            raise ValueError('Non-public photo/source address')
        with requests.Session() as session:
            session.trust_env = False
            with session.get(url, headers={'User-Agent':'Mozilla/5.0',
                    'Accept':'image/*' if image else 'text/html',
                    'Referer':'https://search.naver.com/'}, timeout=(8, 15),
                    allow_redirects=False, stream=True) as response:
                if response.status_code in (301,302,303,307,308):
                    url = urljoin(url, response.headers['Location']); continue
                response.raise_for_status()
                content_type = response.headers.get('Content-Type','').lower()
                if image and not content_type.startswith('image/'):
                    raise ValueError('Photo response is not an image')
                if not image and 'html' not in content_type and not content_type.startswith('text/'):
                    raise ValueError('Source response is not HTML/text')
                chunks=[]; size=0
                for chunk in response.iter_content(65536):
                    size += len(chunk)
                    if size > (25*1024*1024 if image else 2_000_000):
                        raise ValueError('Photo/source response too large')
                    chunks.append(chunk)
                return b''.join(chunks), url
    raise ValueError('Photo/source redirect limit')


def image_items(html):
    """Original PC image-search items arrays, parsed with a JSON decoder."""
    result=[]; decoder=json.JSONDecoder()
    for match in re.finditer(r'items:\s*\[', html):
        try: items, _ = decoder.raw_decode(html[match.end()-1:])
        except ValueError: continue
        if isinstance(items,list):
            result.extend(r for r in items if isinstance(r,dict) and r.get('type','image')=='image')
    return result


def search_images(query):
    global _search_at
    if query in _search_cache:
        return _search_cache[query]
    time.sleep(max(0, .4-(time.monotonic()-_search_at)))
    _search_at = time.monotonic()
    body, url = fetch_public('https://search.naver.com/search.naver?where=image&query='+quote(query))
    result=image_items(body.decode('utf-8',errors='replace')), {'query':query,'url':url,'htmlSha256':digest(body)}
    _search_cache[query]=result
    return result


def ensure_slots(blocks, keyword, minimum=7, maximum=8):
    """Port of public/image-slots.js; explicit model slots stay in their positions."""
    def heading(b): return b and b.get('kind')=='heading' and b.get('text','').strip() and '기본정보' not in b['text']
    def text(b): return b and b.get('kind')=='text' and b.get('text','').strip() and not any(b.get(k) for k in ('_cta','_closing','_disclosure'))
    def image(b): return b and b.get('kind')=='image'
    rows=[]
    for b in deepcopy(blocks):
        if text(b): rows.extend({**b,'text':p.strip()} for p in re.split(r'\n\s*\n', b['text']) if p.strip())
        else: rows.append(b)
    queries=list(dict.fromkeys(b.get('searchQuery','').strip() for b in rows if image(b) and b.get('searchQuery','').strip())) or [keyword]
    rows=[b for i,b in enumerate(rows) if not (image(b) and i+1<len(rows) and heading(rows[i+1]))]
    rows=[b for i,b in enumerate(rows) if not (image(b) and i>0 and image(rows[i-1]))]
    added=0
    while sum(image(b) for b in rows)<min(minimum,maximum):
        heads=[]
        for i,b in enumerate(rows):
            if heading(b): heads.append({'head':i,'body':[]})
            elif heads and text(b): heads[-1]['body'].append(i)
        def free(i): return not image(rows[i]) and (i+1>=len(rows) or not image(rows[i+1]))
        def middle(i): return free(i) and i+1<len(rows) and text(rows[i+1])
        at=-1
        for n,h in enumerate(heads):
            end=heads[n+1]['head'] if n+1<len(heads) else len(rows)
            if not any(image(b) for b in rows[h['head']+1:end]) and free(h['head']): at=h['head']; break
        first=heads[0]['head'] if heads else len(rows)
        intro=[i for i in range(first) if text(rows[i])]
        if at<0 and intro and not any(image(b) for b in rows[:first]) and middle(intro[0]): at=intro[0]
        if at<0:
            choices=[]
            for n,h in enumerate(heads):
                positions=[i for i in h['body'] if middle(i)]
                end=heads[n+1]['head'] if n+1<len(heads) else len(rows)
                if positions: choices.append((sum(image(b) for b in rows[h['head']:end]),positions[(len(positions)-1)//2]))
            if choices: at=min(choices,key=lambda c:c[0])[1]
        if at<0: at=next((i for i in range(first,len(rows)) if text(rows[i]) and middle(i)),-1)
        if at<0: break
        previous=next((b for b in reversed(rows[:at+1]) if heading(b)),{})
        rows.insert(at+1,{'kind':'image','searchQuery':queries[added%len(queries)],'imageHint':previous.get('text',''),'_added':True})
        added+=1
    return rows


def validate_post(post):
    if not isinstance(post,dict) or not str(post.get('recommendedTitle') or post.get('title') or '').strip():
        raise ValueError('B draft title missing')
    rows=post.get('blocks')
    if not isinstance(rows,list) or not any(b.get('kind')=='text' and b.get('text','').strip() for b in rows):
        raise ValueError('B draft body missing')
    if any(b.get('kind') not in ('heading','text','image','table','qna') for b in rows):
        raise ValueError('B unsupported block')
    return post


def body_length(post):
    return sum(len(re.sub(r'\r?\n','',b.get('text',''))) for b in post['blocks'] if b['kind']=='text')


def mobile(text):
    output=[]
    for paragraph in re.split(r'\n\s*\n',text):
        sentences=re.split(r'(?<=[.!?…])\s+(?!\d)',paragraph.strip()); current=''
        for sentence in sentences:
            if current and len(current+' '+sentence)>100: output.append(current);current=''
            current=(current+' '+sentence).strip()
        if current:output.append(current)
    return '\n\n'.join(output)


def research_context(keyword, folder, provided_sources):
    """Original supplied-source branch plus recent-news -> background dossier.

    Search snippets retain their discovery status. Only fetched article bodies
    are appended to the host's factual evidence snapshot.
    """
    cached=load(folder/'b-research.json')
    if cached.get('keyword')==keyword:return cached
    from common.source_discovery import public_text
    articles=[];background=[];errors=[];seen=set();rejected=0
    terms=re.findall(r'[가-힣A-Za-z0-9]{2,}',keyword)
    def matches(text):
        body=re.sub(r'\s+','',text)
        found=lambda term:term in body or len(term)>=3 and term[:-1] in body
        if not terms:return True
        if any(re.fullmatch(r'\d+[회화]',term) and not found(term) for term in terms):return False
        longest=max((t for t in terms if not re.fullmatch(r'\d+[회화]',t)),key=len,default=terms[0])
        count=sum(found(t) for t in terms)
        return found(longest) and count>=(len(terms)+1)//2 if len(terms)<=4 else count>=min(3,len(terms))
    try:
        raw,_=fetch_public('https://m.search.naver.com/search.naver?where=m_news&sort=1&query='+quote(keyword))
        soup=BeautifulSoup(raw,'html.parser');links=[]
        for a in soup.select('a[href]'):
            url=a['href']
            if 'naver.com' in url and '/article/' in url and url not in links:links.append(url)
            if len(links)>=5:break
        for url in links[:4]:
            try:
                source=public_text(url)
                title=next((a.get_text(' ',strip=True) for a in soup.select('a[href]') if a['href']==url and a.get_text(strip=True)),urlsplit(url).hostname)
                if len(source['text'])<=60 or not matches(title+' '+source['text']):rejected+=1;continue
                if title in seen:continue
                seen.add(title);articles.append({**source,'title':title,'body':source['text'][:2200],
                    'press':urlsplit(source['url']).hostname})
            except (requests.RequestException,ValueError,OSError) as exc:errors.append(str(exc)[:200])
        raw,_=fetch_public('https://m.search.naver.com/search.naver?query='+quote(keyword))
        soup=BeautifulSoup(raw,'html.parser')
        for node in soup.select('[class*="sds-comps-text"]'):
            text=node.get_text(' ',strip=True)
            if len(text)>25 and text not in background:background.append(text)
            if len(background)>=6:break
    except (requests.RequestException,ValueError,OSError) as exc:errors.append(str(exc)[:200])
    news='\n\n'.join(f"[기사 {i+1}] ({s['press']}) {s['title']}\n\n본문: {s['body']}" for i,s in enumerate(articles))
    backdrop='\n\n'.join(f'[배경 {i+1}] {text}' for i,text in enumerate(background))
    result={'keyword':keyword,'articles':articles,'backgroundSnippets':background,'blogNotes':[],
        'noBlogs':bool(provided_sources),'rejected':rejected,'errors':errors,
        'factText':news,'backgroundText':backdrop,
        'fullDossier':'■ 확인된 사실 — 최근 기사와 공식 발표:\n'+(news or '검색에서 기사 본문을 가져오지 못했습니다. 확인된 사실처럼 쓰지 마세요.')
            +'\n\n■ 배경 자료 — 인물 이력·사건 경위·관련 지식·대중 반응:\n'+(backdrop or '더 찾은 배경 근거가 없습니다.'),
        'backgroundEvidenceStatus':'discovery_only; not a fetched primary source',
        'sourceInputMode':'provided_public_source', 'collectedAt':datetime.now(timezone.utc).isoformat()}
    write(folder/'b-research.json',result)
    if articles:
        snapshot=load(folder/'research.json')
        for source in articles:
            if not any(s['url']==source['url'] for s in snapshot.get('sources',[])):
                snapshot.setdefault('sources',[]).append(source)
        write(folder/'research.json',snapshot)
    return result


def write_post(folder, keyword, sources):
    from common.llm_client import generate_json
    rules,contract,_=source_instructions()
    instructions=rules+'\n'+contract+'\n'+original_search_rules()
    context_research=research_context(keyword,folder,sources)
    payload={'today':datetime.now().date().isoformat(),'keyword':keyword,'source':sources[0] if sources else None,
             'related':[],'requestedTitle':None,'memo':'',
             'research':context_research['fullDossier'],
             'providedAdditionalSources':[{'title':s.get('title',''),'url':s['url'],'text':s['text'][:15000]} for s in sources[1:]]}
    # _skip_memory prevents company A writer instructions from contaminating B.
    def call(prompt,stage):
        result=generate_json(prompt,agent_slot='workflow_b_'+stage,audit_directory=folder/('b-'+stage+'-audit'),
                             timeout_seconds=600,_skip_memory=True,allow_provider_recovery=False)
        if isinstance(result,dict) and set(result)=={'json'}:result=json.loads(result['json'])
        result=validate_post(result);write(folder/('b-'+stage+'.json'),result);return result
    context='\n입력 자료:\n'+json.dumps(payload,ensure_ascii=False)
    draft=call(instructions+context,'draft')
    review=instructions+'\n완성 초안 최종 교정: 구성 재설계 없이 사실·불필요 주장·분량·형식만 검사한다. image 블록 수·위치·검색어 유지. 제공 자료 밖 주장은 삭제한다.'
    post=call(review+context+'\n초안:'+json.dumps(draft,ensure_ascii=False),'polish')
    if body_length(post)<1500 or body_length(post)>2000:
        post=call(review+'\n본문을 1600~1900자로 맞춘다. 반복·새 사실 생성 금지. 제목·소제목 유지.'+context+'\n원고:'+json.dumps(post,ensure_ascii=False),'length')
    if body_length(post)<800 or not any(b['kind'] in ('heading','image') for b in post['blocks']):
        raise ValueError('B original assertRealPost failed')
    for b in post['blocks']:
        if b['kind']=='text': b['text']=mobile(b['text'])
    post['blocks']=ensure_slots(post['blocks'],keyword)
    write(folder/'b-slotted-post.json',post)
    return post


def dhash(image):
    image=image.convert('L').resize((9,8)); pixels=list(image.getdata())
    return sum((pixels[y*9+x]>pixels[y*9+x+1]) << (y*8+x) for y in range(8) for x in range(8))


def photo_candidates(slot, keyword, folder, index):
    query=re.sub(r'[^가-힣A-Za-z0-9\s]',' ',slot.get('searchQuery','')).strip()[:160] or keyword
    queries=list(dict.fromkeys([query,keyword,keyword.split()[0]+' 이용자',keyword.split()[0]+' 요금',keyword.split()[0]+' 구독',keyword+' 포토']))
    found=[];seen=set();observations=[]
    for q in queries:
        try: rows,receipt=search_images(q);observations.append(receipt)
        except (requests.RequestException,ValueError,OSError) as exc:
            observations.append({'query':q,'error':str(exc)[:250]});continue
        for r in rows:
            title=r.get('title','');url=r.get('originalUrl') or r.get('viewerThumb') or r.get('thumb')
            if r.get('section')!='news' or not title or GRAPHIC.search(title) or EVENT.search(title):continue
            if not url or url in seen or UI.search(url) or re.search(r'조선|chosun',title+url+r.get('writerTitle',''),re.I):continue
            if r.get('orgWidth') and r.get('orgHeight'):
                w,h=float(r['orgWidth']),float(r['orgHeight'])
                if w<250 or h<200 or not .31<=w/h<=3.2:continue
            seen.add(url);found.append({'url':url,'title':title,'articleUrl':r.get('link',''),
                'fallbackUrl':r.get('viewerThumb') or r.get('thumb') or url,
                'press':r.get('writerTitle') or r.get('source') or urlsplit(r.get('link') or url).hostname,
                'heading':slot.get('heading',''),'hint':slot.get('imageHint','')})
            if len(found)>=8:break
        if len(found)>=8:break
    write(folder/f'b-search-{index}.json',{'queries':observations,'candidates':found})
    return found


def decide(row):
    return (all(row.get(k) is True for k in ('inspected','isPhoto','relevant','headingMatch'))
        and all(row.get(k) is False for k in ('chart','table','infographic','logo','advertisement'))
        and type(row.get('confidence')) in (int,float) and .65<=row['confidence']<=1
        and type(row.get('textAreaRatio')) in (int,float) and 0<=row['textAreaRatio']<.2)


def choose_photo(slot, keyword, folder, index, used):
    from common.llm_client import generate_json
    _,_,vision=source_instructions()
    candidates=photo_candidates(slot,keyword,folder,index); downloaded=[]
    cache=folder/'b-downloads';cache.mkdir(exist_ok=True)
    for c in candidates:
        try:
            try:data,final=fetch_public(c['url'],image=True)
            except (requests.RequestException,ValueError,OSError):
                data,final=fetch_public(c['fallbackUrl'],image=True)
            with Image.open(BytesIO(data)) as original:
                w,h=original.size
                if w*h>40_000_000 or w<300 or h<200 or not .31<=w/h<=3.2:continue
                original.load()
                phash=dhash(original)
                if any((phash^old).bit_count()<=5 for old in used):continue
                target=cache/(digest(data)+'.jpg')
                raw_target=cache/(digest(data)+'.original')
                raw_target.write_bytes(data)
                original.convert('RGB').save(target,format='JPEG',quality=92)
            if any(r['sha256']==digest(target.read_bytes()) for r in downloaded):continue
            downloaded.append({**c,'path':str(target),'sha256':digest(target.read_bytes()),
                'downloadSha256':digest(data),'originalPath':str(raw_target),
                'finalUrl':final,'phash':phash,'width':w,'height':h})
        except (requests.RequestException,ValueError,OSError,Image.DecompressionBombError):continue
    if not downloaded:return None
    response=generate_json(vision+json.dumps({'subject':keyword,'keyword':keyword,'infoTopic':True},ensure_ascii=False)
        +'\nCandidates:'+json.dumps([{**r,'index':i,'nearbyText':slot.get('near','')} for i,r in enumerate(downloaded)],ensure_ascii=False),
        images=[r['path'] for r in downloaded],agent_slot='workflow_b_photo_review',
        audit_directory=folder/f'b-vision-{index}-audit',timeout_seconds=300,_skip_memory=True,allow_provider_recovery=False)
    if isinstance(response,dict) and set(response)=={'json'}:response=json.loads(response['json'])
    write(folder/f'b-vision-{index}.json',{'input':downloaded,'response':response})
    rows=response.get('results',[])
    for i,c in enumerate(downloaded):
        match=[r for r in rows if r.get('index')==i]
        if len(match)!=1 or not decide(match[0]):continue
        reviewed=match[0]
        if re.search(r'조선|chosun',reviewed.get('sourceMark',''),re.I):continue
        used.add(c['phash'])
        target=folder/'images'/f'b-photo-{index}.jpg';target.parent.mkdir(exist_ok=True)
        target.write_bytes(Path(c['path']).read_bytes())
        return {**c,'path':str(target),'review':reviewed,'origin':'download',
                'collectedAt':datetime.now(timezone.utc).isoformat()}
    return None


def verify(document,plan,folder,engine):
    if plan.get('workflowProtocol')!=PROTOCOL or plan.get('documentSha256')!=engine.document_fingerprint(document):
        raise ValueError('B download plan/document changed')
    for asset in plan.get('assets',[]):
        path=(Path(folder)/'images'/asset['file']).resolve()
        if not path.is_relative_to((Path(folder)/'images').resolve()) or digest(path.read_bytes())!=asset['sha256']:
            raise ValueError('B downloaded photo changed')
        source=asset['downloadEvidence']
        original=Path(source.get('originalPath','')).resolve()
        if (source.get('origin')!='download' or not original.is_relative_to((Path(folder)/'b-downloads').resolve())
                or not original.is_file() or digest(original.read_bytes())!=source.get('downloadSha256')):
            raise ValueError('B original download evidence changed')
        raw=load(Path(folder)/f"b-vision-{source['slot']}.json")
        matches=[r for r in raw.get('input',[]) if r.get('sha256')==asset['sha256']]
        if len(matches)!=1 or not decide(source['review']) or source['review'] not in raw.get('response',{}).get('results',[]):
            raise ValueError('B original-pixel review binding missing')
    report=engine.validate_document(document,plan,Path(folder)/'images')
    if not report['ok']:raise ValueError('B document format: '+json.dumps(report['errors'],ensure_ascii=False))
    return {'status':'ready','origin':'download','assets':plan['assets']}


def prepare(engine,account_key,folder,keyword):
    from common.source_discovery import research
    from common.naver_reader import ensure_reader_review, normalize_links
    from common.content_quality import ensure_publication_review
    from common.llm_client import generate_json
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    account=dict(engine.ACCOUNT_MAP[account_key]);identity={'account':account_key,'blogId':account['blog_id']}
    receipt=load(folder/'reservation-evidence.json')
    if receipt and receipt.get('submissionStatus') not in ('submitting','submission_unknown','verified_reserved'):
        raise ValueError('B artifact has a receipt; reconcile before preparing')
    if receipt:
        document=load(folder/'editor-content.json');plan=load(folder/'photo-plan.json')
        if (load(folder/'identity.json')!=identity or receipt.get('account')!=account_key
                or receipt.get('title')!=document.get('title')):
            raise ValueError('B submitted artifact identity changed')
        verify(document,plan,folder,engine)
        return account,folder,document,plan
    if load(folder/'identity.json') not in ({},identity):raise ValueError('B identity changed')
    write(folder/'identity.json',identity)
    if not (folder/'b-protocol-evidence.json').is_file():write(folder/'b-protocol-evidence.json',protocol_evidence())
    if (folder/'editor-content.json').is_file() and (folder/'photo-plan.json').is_file():
        document=load(folder/'editor-content.json');plan=load(folder/'photo-plan.json')
        from common.editorial_recovery import rebind_reviewed_download
        plan=rebind_reviewed_download(document,plan,folder,engine,verify)
        verify(document,plan,folder,engine)
    else:
        sources=research(keyword,folder,exact_query=True)
        if not sources:raise ValueError('B no collected research; no invented draft')
        post=load(folder/'b-slotted-post.json') or write_post(folder,keyword,sources)
        document={'title':post.get('recommendedTitle') or post['title'],'published':False,'blocks':[]}
        assets=[];used=set();slot=0;heading=document['title'];missing=[]
        for b in post['blocks']:
            kind=b['kind']
            if kind=='heading':heading=b['text'];document['blocks'].append({'type':'heading','text':b['text']})
            elif kind=='text':
                document['blocks'].extend({'type':'text','text':p.strip()} for p in re.split(r'\n\s*\n',b['text']) if p.strip())
            elif kind=='table':document['blocks'].append({'type':'table','rows':[b['columns']]+b['rows']})
            elif kind=='qna':document['blocks'].append({'type':'text','text':str(b.get('question',''))+'\n'+str(b.get('answer',''))})
            elif kind=='image':
                near=next((r.get('text','') for r in reversed(document['blocks']) if r['type']=='text'),'')
                photo=choose_photo({**b,'heading':heading,'near':near},keyword,folder,slot,used)
                if photo:
                    caption=photo['review'].get('scene') or photo['title']
                    clean=lambda t:re.sub(r'[|｜/\\\r\n]',' ',str(t)).strip()
                    asset={'id':len(assets),'file':Path(photo['path']).name,'description':clean(caption),
                           'credit':clean(photo['press']),'sha256':photo['sha256'],'sourceUrl':photo['articleUrl'],
                           'downloadEvidence':{**photo,'slot':slot}}
                    assets.append(asset);document['blocks'].append({'type':'image','id':asset['id'],'file':asset['file'],
                        'alt':asset['description'],'caption':asset['description']+'｜'+asset['credit']})
                else:missing.append({'slot':slot,'query':b.get('searchQuery'),'reason':'no_pixel_approved_news_photo'})
                slot+=1
        tags=list(dict.fromkeys('#'+re.sub(r'[^가-힣A-Za-z0-9_]','',str(t).lstrip('#')) for t in post.get('hashtags',[])))
        tags=[t for t in tags if len(t)>1]
        if not tags:raise ValueError('B tags missing')
        document['blocks'].append({'type':'tags','text':' '.join(tags)})
        normalize_links(document,sources)
        plan={'version':1,'workflowProtocol':PROTOCOL,'main_keyword':keyword,'signoff':'','assets':assets,
              'representative_file':assets[0]['file'] if assets else '',
              'documentSha256':engine.document_fingerprint(document)}
        write(folder/'b-image-realization.json',{'origin':'download','slots':slot,'approved':len(assets),'missing':missing})
        # The original app also records unfilled image slots; it does not fabricate a replacement.
        write(folder/'photo-plan.json',plan);write(folder/'editor-content.json',document)
        verify(document,plan,folder,engine)
    report=engine.validate_document(document,plan,folder/'images');write(folder/'format-check.json',report)
    if not receipt:
        # The common factual reviewer normally receives text. B's photo captions
        # need the downloaded pixels and their independently bound source record.
        photo_evidence=[{'kind':'downloaded_photo_pixels','file':a['file'],'sha256':a['sha256'],
            'sourceUrl':a['sourceUrl'],'imageUrl':a['downloadEvidence']['finalUrl'],
            'observedSearchCaption':a['downloadEvidence']['title'],
            'pixelReview':a['downloadEvidence']['review']} for a in plan['assets']]
        snapshot=load(folder/'research.json')
        existing=[e for e in snapshot.get('publisherEvidence',[]) if e.get('kind')!='downloaded_photo_pixels']
        if snapshot.get('publisherEvidence')!=existing+photo_evidence:
            old_review=load(folder/'claim-review.json')
            if old_review:write(folder/'b-claim-review-before-pixel-evidence.json',old_review)
            snapshot['publisherEvidence']=existing+photo_evidence
            write(folder/'research.json',snapshot)
        def review_with_photos(prompt,*args,**kwargs):
            if plan['assets']:
                kwargs['images']=[str(folder/'images'/a['file']) for a in plan['assets']]
                prompt+='\nAttached photos are the actual downloaded images in publisherEvidence order. Verify descriptive captions against those pixels; scene descriptions are not claims of author experience or evidence of clinical efficacy.'
            return generate_json(prompt,*args,**kwargs)
        from common.editorial_recovery import review_and_repair
        review_and_repair(document,folder,[lambda d:ensure_reader_review(d,folder),
            lambda d:ensure_publication_review(d,folder,generate=review_with_photos)])
        plan['documentSha256']=engine.document_fingerprint(document)
        verify(document,plan,folder,engine)
        write(folder/'photo-plan.json',plan);write(folder/'editor-content.json',document)
    (folder/'preview.html').write_text(engine.render_document(document,plan,folder/'images'),encoding='utf-8')
    return account,folder,document,plan
