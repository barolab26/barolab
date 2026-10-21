"""Observe public research in the existing account browser; never open an editor."""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import parse_qs, urlencode, urlsplit


def _now():
    return datetime.now(timezone.utc).isoformat()


def _sha(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


@contextmanager
def research_browser(account):
    from playwright.sync_api import sync_playwright
    from common.ubuntu_naver_browser import accounts, ensure_account, focus_workflow_window
    port = accounts()[account]['cdp_port']
    ensure_account(port)
    focus_workflow_window(port)
    with sync_playwright() as playwright:
        browser = playwright.chromium.connect_over_cdp(f'http://127.0.0.1:{port}')
        yield browser.contexts[0]
        # Disconnecting Playwright preserves all browser processes and user tabs.


@contextmanager
def public_page(context, url):
    page = next((p for p in context.pages if p.url == url), None)
    owned = page is None
    if owned:
        page = context.new_page()
    try:
        if owned:
            page.goto(url, wait_until='domcontentloaded', timeout=30000)
        page.bring_to_front()
        yield page, owned
    finally:
        if owned and not page.is_closed():
            page.close()


def ranked_posts(rows):
    """Retain observed title-link order; duplicate thumbnails cannot change rank."""
    posts = []
    seen = set()
    for row in rows:
        url = row.get('url', '')
        if not re.fullmatch(r'https://blog\.naver\.com/[A-Za-z0-9_-]+/[0-9]+', url):
            continue
        if not row.get('title', '').strip() or row.get('advertisement'):
            continue
        if url not in seen:
            seen.add(url)
            posts.append({'url': url, 'title': row['title'].strip(), 'observedRank': len(posts) + 1})
        if len(posts) == 3:
            return posts
    raise RuntimeError('Three actual organic blog title results required')


def collect_blog_evidence(account, query):
    if not isinstance(query, str) or not query.strip():
        raise ValueError('A concrete search query is required')
    query = query.strip()
    url = 'https://search.naver.com/search.naver?' + urlencode({'ssc': 'tab.blog.all', 'query': query})
    with research_browser(account) as context:
        with public_page(context, url) as (page, owned):
            page.locator('a[data-heatmap-target=".nblg"] .sds-comps-text-type-headline1').first.wait_for(timeout=15000)
            observed = parse_qs(urlsplit(page.url).query)
            selected_sort = page.locator('[aria-selected="true"]').all_inner_texts()
            if (observed.get('ssc') != ['tab.blog.all'] or observed.get('query') != [query]
                    or '관련도순' not in [v.strip() for v in selected_sort]):
                raise RuntimeError('Actual blog/relevance search surface could not be confirmed')
            rows = page.locator('a[data-heatmap-target=".nblg"]').evaluate_all('''xs => xs.map(a => ({
                url:a.href, title:a.querySelector('.sds-comps-text-type-headline1')?.innerText || '',
                advertisement:!!a.closest('[data-ad-type],.ad_section,.ad_area')
            }))''')
            posts = ranked_posts(rows)
            at = _now()
            serp = {'url': page.url, 'query': query, 'observedAt': at,
                    'text': page.locator('#main_pack').inner_text(),
                    'links': [p['url'] for p in posts], 'owned': owned}
        for post in posts:
            with public_page(context, post['url']) as (page, owned):
                page.locator('#mainFrame').wait_for(timeout=15000)
                frame = page.frame_locator('#mainFrame')
                article = frame.locator('.se-main-container')
                article.wait_for(timeout=15000)
                text = article.inner_text().strip()
                if len(text) < 100:
                    raise RuntimeError('Top-three article body unavailable; do not replace its rank')
                # Keep image/caption placement observations separate from inferred image meaning.
                visuals = article.locator('.se-component.se-image').evaluate_all('''xs => xs.map((x,i)=>({
                    index:i,caption:x.querySelector('.se-caption')?.innerText || '',
                    alt:x.querySelector('img')?.alt || '',
                    precedingText:x.previousElementSibling?.innerText || ''
                }))''')
                post['excerpt'] = {'url': post['url'], 'text': text, 'bodySha256': _sha(text),
                                   'collectedAt': _now(), 'collectionMethod': 'visible_browser_article'}
                post['visualPlacementObservations'] = visuals
                post['owned'] = owned
    return {'account': account, 'query': query, 'searchSurface': 'naver_blog', 'sort': 'relevance',
            'observedAt': at, 'rankScope': 'Observed non-ad blog title order at this time; not a ranking guarantee',
            'serp': serp, 'competitors': posts}


def validate_capture_request(request):
    url = request.get('sourceUrl', '')
    parsed = urlsplit(url)
    host = (parsed.hostname or '').lower()
    if (parsed.scheme != 'https' or parsed.username or parsed.password or parsed.port not in (None, 443)
            or not (host.endswith('.go.kr') or host in ('nhis.or.kr', 'www.nhis.or.kr',
                                                       'longtermcare.or.kr', 'www.longtermcare.or.kr'))
            or any(re.search(r'token|password|secret|credential|session', k, re.I) for k in parse_qs(parsed.query))):
        raise ValueError('Public official source URL required')
    source = request.get('sourceEvidence', {})
    text = source.get('text', '')
    anchors = request.get('anchors')
    if (source.get('url') != url or not text or source.get('bodySha256') != _sha(text)
            or not isinstance(anchors, list) or not 1 <= len(anchors) <= 4
            or any(not isinstance(a, str) or len(a.strip()) < 8 or a not in text for a in anchors)):
        raise ValueError('Capture anchors must exist in hash-verified official evidence')
    for key in ('materialId', 'stepId'):
        if not re.fullmatch(r'[A-Za-z0-9_-]+', str(request.get(key, ''))):
            raise ValueError('Explicit safe material and step identities required')
    if not str(request.get('observation', '')).strip():
        raise ValueError('The requested reader-helping observation is required')
    return url


def capture_official_materials(account, reader_question, requests, folder):
    """Locate source-backed text regions and capture original rendered pixels."""
    from naver_blog_posting.material_assets import load_material_manifest
    from common.ubuntu_naver_browser import accounts
    if account not in accounts():
        raise ValueError('Known account required for official capture destination')
    root = Path(__file__).resolve().parent / 'output'
    folder = Path(folder).resolve()
    if (not folder.is_relative_to((root / account).resolve()) or not reader_question
            or not isinstance(requests, list) or not 1 <= len(requests) <= 12):
        raise ValueError('Account-contained destination and bounded semantic capture requests required')
    for request in requests:
        validate_capture_request(request)
    if len({r['materialId'] for r in requests}) != len(requests):
        raise ValueError('Duplicate capture identities rejected')
    folder.mkdir(parents=True, exist_ok=True)
    materials = []
    with research_browser(account) as context:
        for request in requests:
            with public_page(context, request['sourceUrl']) as (page, owned):
                if page.url != request['sourceUrl']:
                    raise RuntimeError('Redirected official capture requires new source verification')
                page.locator('body').wait_for(timeout=15000)
                page.wait_for_function('''anchors => anchors.every(a =>
                    document.body.innerText.replace(/\\s+/g,' ').includes(a.replace(/\\s+/g,' ')))''',
                    arg=request['anchors'], timeout=15000)
                region = page.evaluate('''anchors => {
                    const norm=s=>s.replace(/\\s+/g,' ').trim();
                    const all=[...document.querySelectorAll('div,section,article,table,ul,ol,p')];
                    const selected=anchors.map(anchor=>all.filter(e=>{
                        const box=e.getBoundingClientRect();
                        return box.width>=100 && box.height>=15 && norm(e.innerText||'').includes(norm(anchor));
                    }).sort((a,b)=>a.innerText.length-b.innerText.length)[0]).map(e=>e?.closest('table') || e?.closest('ul,ol') || e);
                    if(selected.some(e=>!e))return null;
                    const unique=[...new Set(selected)];
                    const boxes=unique.map(e=>e.getBoundingClientRect());
                    const left=Math.min(...boxes.map(b=>b.left)),right=Math.max(...boxes.map(b=>b.right));
                    const top=Math.min(...boxes.map(b=>b.top)),bottom=Math.max(...boxes.map(b=>b.bottom));
                    if(right-left>1800 || bottom-top>1800)return null;
                    if([...document.querySelectorAll('input,textarea')].some(x=>{
                        const b=x.getBoundingClientRect();
                        return b.width>0 && b.height>0 && b.left<right && b.right>left && b.top<bottom && b.bottom>top
                            && (x.value || x.type==='password');
                    }))return null;
                    return {clip:{x:left+scrollX,y:top+scrollY,width:right-left,height:bottom-top},
                            text:unique.map(e=>e.innerText).join('\\n')};
                }''', request['anchors'])
                if not region:
                    raise RuntimeError('No bounded public source region contains all required anchors')
                name = request['materialId'] + '.png'
                path = folder / name
                if path.exists():
                    raise RuntimeError('Capture destination exists; preserve prior evidence in a new run folder')
                page.screenshot(path=str(path), clip=region['clip'], animations='disabled', timeout=15000)
                materials.append({'materialId': request['materialId'], 'stepId': request['stepId'],
                    'source': 'capture', 'filename': name, 'filePath': str(path),
                    'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                    'sourceUrl': request['sourceUrl'], 'capturedAt': _now(),
                    'observation': request['observation'], 'observedText': region['text'],
                    'sourceBodySha256': request['sourceEvidence']['bodySha256'],
                    'sensitiveDataAbsent': True, 'owned': owned})
    path = folder / 'manifest.json'
    if path.exists():
        raise RuntimeError('Existing manifest must not be overwritten')
    path.write_text(json.dumps({'version': 1, 'account': account, 'readerQuestion': reader_question,
                               'materials': materials}, ensure_ascii=False, indent=2), encoding='utf-8')
    return load_material_manifest(path, account=account, roots=[root])
