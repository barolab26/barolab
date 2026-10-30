"""One-pass publishing: research, document, format checks, submit, verify."""

import sys
sys.dont_write_bytecode = True

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

sys.path.insert(0, str(BASE_DIR.parent / 'dashboard'))
sys.path.insert(0, str(BASE_DIR.parent))

import os
import time
import datetime
import json
import requests
import re
import hashlib
import mimetypes
import uuid
import argparse
from contextlib import contextmanager
from bs4 import BeautifulSoup
from common.ego_telemetry import action as ego_action
from common.channel_attribution import is_dummy_rescue_url

def stamp():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()

def published_inventory(base_url, get=None):
    get = get or requests.get
    posts, seen = ([], set())
    for page in range(1, 101):
        try:
            response = get(base_url.rstrip('/') + '/api/posts', params={'page': page, 'limit': 40}, timeout=15)
            response.raise_for_status()
            payload = response.json()
            rows = payload.get('posts', [])
            limit = int(payload.get('limit') or 40)
            if rows and all((row.get('id') in seen for row in rows)):
                raise RuntimeError('전체 목록 페이지 반복')
            for row in rows:
                if row.get('id') not in seen:
                    seen.add(row['id'])
                    if not is_dummy_rescue_url(row.get('slug')):
                        posts.append({k: row.get(k) for k in ('id', 'title', 'slug', 'category', 'excerpt', 'created_at', 'status')})
            if len(rows) < limit:
                break
        except Exception as exc:
            raise RuntimeError('전체 기발행 글 목록 조회 실패') from exc
    else:
        raise RuntimeError('전체 목록 페이지 제한 초과')
    return posts

def duplicate_posts(candidate, posts, own_id=None):
    slug = (candidate.get('topicSlug') or '').casefold()
    title = (candidate.get('title') or candidate.get('mainKeyword') or '').casefold()
    return [p for p in posts if p.get('id') != own_id and (p.get('slug', '').casefold() == slug or p.get('title', '').casefold() == title)]

DATA_DIR = BASE_DIR.parent / 'dashboard/data/cf'

SCHEDULE_JSON = DATA_DIR / 'daily_schedule.json'
STATE_JSON = DATA_DIR / 'pipeline_state.json'
STATUS_JS = DATA_DIR / 'pipeline_status.js'

KEYS_FILE = DATA_DIR / 'secure' / 'cf_blog_keys.json'

def get_api_key(domain: str) -> str:
    from dotenv import dotenv_values
    prefix = domain.split('.')[0].replace('-', '').upper()
    key = dotenv_values(BASE_DIR.parent / '.env').get(prefix + '_CF_API_KEY')
    if key:
        return key
    with open(KEYS_FILE, 'r', encoding='utf-8') as f:
        keys = json.load(f)
    return keys[domain]

def upload_images_to_cf(domain, image_paths):
    api_key = get_api_key(domain)
    headers = {'x-api-key': api_key, 'Authorization': f'Bearer {api_key}'}
    uploaded_urls = []
    for p in image_paths:
        fname = os.path.basename(p)
        print(f'Uploading {fname} to Cloudflare Media CDN ({domain})...', flush=True)
        with open(p, 'rb') as f:
            files = {'file': (fname, f, mimetypes.guess_type(fname)[0] or 'application/octet-stream')}
            with ego_action('api_request', 'cf-image-upload'):
                resp = requests.post(f'https://www.{domain}/api/media/upload', headers=headers, files=files, timeout=30)
            if resp.status_code in [200, 201]:
                data = resp.json()
                media_url = data.get('media', {}).get('url') or data.get('url')
                if not media_url.startswith('http'):
                    media_url = f'https://www.{domain}{media_url}'
                print(f'Uploaded CDN URL: {media_url}', flush=True)
                uploaded_urls.append(media_url)
            else:
                raise RuntimeError(f'Failed to upload {fname}: HTTP {resp.status_code}')
    return uploaded_urls

def registered_categories(domain):
    response = requests.get(f'https://www.{domain}/api/settings', headers={'x-api-key': get_api_key(domain)}, timeout=12)
    if response.status_code in (401, 403):
        from dotenv import dotenv_values
        values = dotenv_values(BASE_DIR.parent / '.env')
        prefix = domain.split('.')[0].replace('-', '').upper()
        password = values.get(prefix + '_CF_ADMIN_PASSWORD')
        if not password:
            raise ValueError(f'{domain} 설정 조회 인증 HTTP {response.status_code}: 해당 사이트 관리자 설정 필요')
        login = requests.post(f'https://www.{domain}/api/auth/login', json={'password': password}, timeout=12, allow_redirects=False)
        if login.status_code != 200 or not login.json().get('token'):
            raise ValueError(f'{domain} 사이트 관리자 인증 실패: 발행 보류')
        response = requests.get(f'https://www.{domain}/api/settings', headers={'Authorization': 'Bearer ' + login.json()['token']}, timeout=12)
    response.raise_for_status()
    categories = [c.strip() for c in response.json()['settings'].get('categories', '').split(',') if c.strip()]
    if not categories:
        raise ValueError('사이트에 등록된 발행 분류가 없습니다')
    return categories

KST = datetime.timezone(datetime.timedelta(hours=9))

ALL_DOMAINS = ['must-good.com', 'baronote.kr', 'must-joy.com', 'maxnote.kr', 'joynote.kr', 'healthcox.com', 'topnote.kr', 'nolplace.com', 'tripmarvel.com', 'daynote.kr', 'smilenote.kr', 'woorinote.kr', 'meganote.kr', 'justinfo.co.kr', 'soulnote.kr', 'must-pick.com']

def save_schedule_file(path, schedule):
    save_live(Path(path), json.dumps(schedule, ensure_ascii=False, indent=2))

def validate_basic_article(article):
    if not isinstance(article, dict):
        raise ValueError('Article must be an object')
    for key in ('title', 'summary', 'category', 'topicSlug', 'contentHtml'):
        if not isinstance(article.get(key), str) or not article[key].strip():
            raise ValueError('Missing article field: ' + key)
    if not re.fullmatch('[a-z0-9][a-z0-9-]{0,179}', article['topicSlug']):
        raise ValueError('Invalid article slug')
    if is_dummy_rescue_url(article['topicSlug']):
        raise ValueError('Reserved synthetic publication slug')
    soup = BeautifulSoup(article['contentHtml'], 'html.parser')
    if not soup.get_text(' ', strip=True) or not soup.find(['p', 'h2', 'table']):
        raise ValueError('Article needs readable HTML blocks')
    if soup.find(['script', 'iframe', 'form', 'object', 'embed']):
        raise ValueError('Active HTML is not allowed in an article')
    for tag in soup.find_all(True):
        for key, value in tag.attrs.items():
            if key.lower().startswith('on') or (key.lower() in ('href', 'src') and str(value).lower().lstrip().startswith(('javascript:', 'data:text/html'))):
                raise ValueError('Unsafe HTML attribute')
    return article

from common.source_discovery import research as basic_research

def ensure_article_images(article, folder, domain=None):
    from html import escape
    from common.dashboard_jobs import write
    from common.flow_images import generate as flow_image

    folder = Path(folder)
    existing_plans = [p for p in (article.get('imagePlans') or []) if isinstance(p, dict) and p.get('filename')]
    if existing_plans and all((folder / 'images' / p['filename']).is_file() for p in existing_plans) and ('{{IMAGE_0}}' in article.get('contentHtml', '') or '<img' in article.get('contentHtml', '')):
        return article

    if domain:
        try:
            basic_progress(domain, 5, '이미지·썸네일 생성', 75, article.get('title', domain))
        except Exception:
            pass

    hero_img = flow_image(article['title'], article['summary'], folder, custom_prompt=article.get('imagePrompt'), filename='flow-hero.png', source_index=0)
    hero_caption = (article.get('imageCaption') or f"{article.get('mainKeyword') or article['title']} 핵심 요약").strip()
    plans = [{'filename': hero_img.name, 'source': 'generated', 'caption': hero_caption, 'role': 'thumbnail'}]

    soup = BeautifulSoup(article.get('contentHtml', ''), 'html.parser')
    for old_fig in soup.find_all('figure'):
        if '{{IMAGE_' in str(old_fig):
            old_fig.decompose()

    h2_tags = soup.find_all('h2')
    sec_specs = [s for s in (article.get('sectionImages') or []) if isinstance(s, dict) and ((s.get('imagePrompt') or '').strip() or (s.get('sectionHeading') or '').strip())]
    if not sec_specs and len(h2_tags) >= 2:
        mid_h2 = h2_tags[len(h2_tags) // 2]
        h_txt = mid_h2.get_text(' ', strip=True)
        sec_specs = [{'sectionHeading': h_txt, 'imagePrompt': '', 'imageCaption': f'{h_txt} 핵심 확인 포인트'}]

    for idx, spec in enumerate(sec_specs[:2], 1):
        sec_fname = f'flow-section-{idx}.png'
        sec_title = (spec.get('sectionHeading') or article['title']).strip()
        sec_cap = (spec.get('imageCaption') or f'{sec_title} 핵심 포인트').strip()
        sec_img = flow_image(sec_title, sec_cap + ' ' + article['summary'], folder, custom_prompt=spec.get('imagePrompt'), filename=sec_fname, source_index=idx)
        plans.append({'filename': sec_img.name, 'source': 'generated', 'caption': sec_cap, 'sectionHeading': sec_title, 'role': 'section'})

    def _make_figure_html(idx, caption, eager=False):
        load_attr = 'eager' if eager else 'lazy'
        return BeautifulSoup(
            f'<figure class="post-image" style="margin:24px 0;text-align:center;">'
            f'<img src="{{{{IMAGE_{idx}}}}}" alt="{escape(caption)}" style="max-width:100%;height:auto;border-radius:12px;" loading="{load_attr}">'
            f'<figcaption class="image-caption" style="margin-top:8px;font-size:0.9rem;color:#64748b;">{escape(caption)}</figcaption>'
            f'</figure>',
            'html.parser',
        ).figure

    # Insert IMAGE_0 right after the opening intro paragraph (or before first h2)
    hero_fig = _make_figure_html(0, hero_caption, eager=True)
    first_h2 = h2_tags[0] if h2_tags else None
    first_p = soup.find('p')
    if first_h2 is not None:
        first_h2.insert_before(hero_fig)
    elif first_p is not None:
        first_p.insert_after(hero_fig)
    else:
        soup.insert(0, hero_fig)

    # Insert section images naturally inside their corresponding h2 sections
    for idx, plan in enumerate(plans[1:], 1):
        sec_fig = _make_figure_html(idx, plan['caption'], eager=False)
        target_heading = (plan.get('sectionHeading') or '').strip()
        matched_h2 = next((h for h in h2_tags if target_heading and (target_heading in h.get_text(' ', strip=True) or h.get_text(' ', strip=True) in target_heading)), None)
        if matched_h2 is None and h2_tags:
            matched_h2 = h2_tags[min(idx, len(h2_tags) - 1)]
        if matched_h2 is not None:
            next_p = matched_h2.find_next_sibling('p')
            if next_p is not None:
                next_p.insert_after(sec_fig)
            else:
                matched_h2.insert_after(sec_fig)
        else:
            soup.append(sec_fig)

    article['imagePlans'] = plans
    from common.cf_tables import inject_interactive_widget
    article['contentHtml'] = inject_interactive_widget(str(soup), article.get('title', ''))
    validate_basic_article(article)
    write(folder / 'article.json', article)
    write(folder / 'editor-content.json', article)
    write(folder / 'photo-plan.json', {
        'assets': plans,
        'medium': 'editorial-image',
        'sha256': hashlib.sha256(hero_img.read_bytes()).hexdigest(),
    })
    return article


def basic_article(domain, item, folder):
    path = folder / 'article.json'
    if path.is_file():
        handoff = folder / 'handoff.json'
        if handoff.is_file() and json.loads(handoff.read_text(encoding='utf-8')).get('domain') not in (None, domain):
            raise ValueError('Saved article belongs to another domain')
        article = validate_basic_article(json.loads(path.read_text(encoding='utf-8')))
        return ensure_article_images(article, folder, domain=domain)
    keyword = item.get('mainKeyword') or item.get('title') or item.get('topic') or item.get('category') or domain
    basic_progress(domain,2,'리서치',25,str(keyword))
    sources = basic_research(keyword, folder)
    from common.llm_client import generate_json
    from common.dashboard_jobs import write
    sec_img_schema = {
        'type': 'object',
        'properties': {
            'sectionHeading': {'type': 'string'},
            'imagePrompt': {'type': 'string'},
            'imageCaption': {'type': 'string'},
        },
        'required': ['sectionHeading', 'imagePrompt', 'imageCaption'],
        'additionalProperties': False,
    }
    schema = {
        'type': 'object',
        'properties': {
            **{key: {'type': 'string'} for key in ('title', 'summary', 'category', 'topicSlug', 'contentHtml', 'imagePrompt', 'imageCaption')},
            'sectionImages': {'type': 'array', 'items': sec_img_schema},
        },
        'required': ['title', 'summary', 'category', 'topicSlug', 'contentHtml', 'imagePrompt', 'imageCaption', 'sectionImages'],
        'additionalProperties': False,
    }
    prompt = (
        '독자가 끝까지 읽고 행동하게 만드는 진짜 사람의 한국어 블로그 원고를 작성한다. "공무원 공고문 요약 매크로"나 딱딱한 리서치 보고서 말투는 절대 쓰지 않는다.\n'
        '[4대 집필 원칙 (필수 준수)]\n'
        '1. 제목(title): 공공기관 보고서식 제목("[키워드], 조건·확인 순서")을 절대 쓰지 마라. 독자가 보자마자 "어, 이거 내 얘기잖아?" 하고 클릭하게 만드는 구체적 반려/실패 함정, 한 끗 차이 기준, 3분 자가진단형 제목으로 작성하라.\n'
        '2. 도입부(contentHtml 첫 1~2문단): 교과서적 정의나 "이 글은 제공된 자료를 정리했습니다" 같은 메타 브리핑으로 시작하면 3초 만에 이탈한다. 밤늦게 검색창을 켜는 독자의 진짜 통증(Pain Point: 막막함, 억울함, 헛걸음 걱정, 헷갈리는 현실 상황)에 깊이 공감하며 시작하고, 이 글에서 바로 해결해 줄 핵심 기준을 딱 짚어라.\n'
        '3. 본문(contentHtml — 한 끗 차이 실전 사례 + 3초 판독기 표 + 모바일 2~3줄 호흡):\n'
        '   - 어려운 용어를 사전처럼 나열하지 말고 독자가 스마트폰을 보며 내 상황에 바로 대입할 수 있게 써라.\n'
        '   - 구체적인 대비 사례(예: "A는 안 되지만 B는 됩니다", "X 코드는 탈락이지만 Y 코드는 통과입니다")를 본문에 녹여 독자가 무릎을 치게 만들어라.\n'
        '   - 본문 중간에는 설명충용 표가 아니라 내 조건/상황을 손가락으로 짚어보며 "된다/안 된다/유리하다/불리하다"를 3초 만에 판별할 수 있는 실전 자가진단 판독기 <table>을 반드시 포함하라.\n'
        '   - 한 문단(<p>)은 스마트폰 화면 기준 2~3줄이 넘지 않게 호흡을 짧고 리듬감 있게 끊어 쳐라.\n'
        '4. 마무리(Action Item): 마지막 문단에 "해설 글이며 개인별 조회 서비스가 아닙니다", "공식 공고를 참고하세요" 같은 관료적 면책 문구를 절대 넣지 마라. 대신 독자가 글 읽기를 마친 직후 오늘 당장(또는 이번 주말에 미리) 실행할 수 있는 구체적 행동 지침(Action Item: 먼저 꺼내볼 서류, 미리 조회할 메뉴, 체크할 항목 등)으로 힘 있게 닫아라.\n'
        '[시각 자료 및 기술 규칙]\n'
        '- 대표 썸네일용 imagePrompt와 본문 핵심 <h2> 소제목 구간(1~2곳)을 위한 sectionImages의 imagePrompt는 구체적인 영어 문장(English prompt)으로 작성하되, 원고의 구체적 상황·장면·피사체·조명·분위기를 고해상도 실사 에디토리얼 사진(high-resolution editorial photography) 스타일로 묘사하거나(이미지 내 글자/텍스트/로고/문서화면 절대 제외), 리서치 원본 웹페이지 증거 캡쳐가 더 적합한 경우 "RESEARCH_CAPTURE"로 지정한다.\n'
        '- imageCaption과 sectionImages.imageCaption에는 독자에게 자연스러운 한국어 사진 설명을 한 줄로 작성하고, sectionImages.sectionHeading에는 해당 이미지가 들어갈 본문 <h2> 소제목 텍스트를 정확히 기입한다.\n'
        '- topicSlug는 영문 소문자·하이픈 조합으로 작성하며, 등록된 categories 중 하나를 선택한다.\n'
        '[절대 금지 가드레일]\n'
        '- 수집 자료(research)에 없는 허위 사실·수치 날조 금지 (단, 자료의 한계를 변명하는 "제공된 자료에서는 알 수 없습니다", "이 글은 제공된 안내를 바탕으로..." 같은 리서치 메타 발언은 본문에 절대 노출 금지)\n'
        '- AI/봇 메타 발언("AI 생성", "참고사진") 및 면피성 문구("공식 공고 참고", "조회 서비스가 아닙니다") 절대 금지.\n'
        + json.dumps({'domain': domain, 'topic': keyword, 'categories': registered_categories(domain), 'research': sources}, ensure_ascii=False)
    )
    basic_progress(domain,4,'원고 작성',55,str(keyword))
    article = validate_basic_article(generate_json(prompt, agent_slot='cf_pipeline', response_schema=schema, audit_directory=folder / 'model-audit', timeout_seconds=600))
    write(path, article)
    return ensure_article_images(article, folder, domain=domain)

def ping_indexnow(domain, public_url):
    key = hashlib.sha256(f'barolab-indexnow-{domain}'.encode('utf-8')).hexdigest()[:32]
    endpoints = (
        f'https://api.indexnow.org/indexnow?url={requests.utils.quote(public_url, safe="")}&key={key}',
        f'https://www.bing.com/indexnow?url={requests.utils.quote(public_url, safe="")}&key={key}',
        f'https://www.google.com/ping?sitemap={requests.utils.quote(f"https://www.{domain}/sitemap.xml", safe="")}',
    )
    results = []
    for ep in endpoints:
        try:
            r = requests.get(ep, timeout=6)
            results.append({'endpoint': ep.split('?')[0], 'httpStatus': r.status_code})
        except Exception as exc:
            results.append({'endpoint': ep.split('?')[0], 'error': type(exc).__name__})
    try:
        from common.dashboard_jobs import write
        log_path = DATA_DIR / 'indexnow_log.json'
        prev = json.loads(log_path.read_text(encoding='utf-8')) if log_path.is_file() else {'pings': []}
        prev['pings'] = (prev.get('pings') or [])[-199:] + [{'domain': domain, 'url': public_url, 'pingedAt': stamp(), 'results': results}]
        write(log_path, prev)
    except Exception:
        pass
    return results

def basic_public_receipt(domain, article, response, folder):
    from common.dashboard_jobs import write
    response.raise_for_status()
    payload = response.json()
    post = payload.get('post') or payload
    if not post.get('id'):
        raise RuntimeError('Publication response missing post ID; reconcile before retrying')
    slug = post.get('slug') or article['topicSlug']
    if not re.fullmatch('[a-z0-9][a-z0-9-]{0,179}', slug):
        raise RuntimeError('Publication returned invalid slug')
    url = f'https://www.{domain}/{slug}'
    receipt = {'state': 'accepted', 'domain': domain, 'postId': post['id'], 'publicUrl': url, 'title': article['title'], 'acceptedAt': stamp(), 'publicPublicationVerified': False}
    write(folder / 'publication-receipt.json', receipt)
    public = requests.get(url, timeout=20)
    public.raise_for_status()
    text = BeautifulSoup(public.text, 'html.parser').get_text(' ', strip=True)
    if public.status_code != 200 or article['title'] not in text:
        raise RuntimeError('Accepted post awaiting public title verification')
    index_pings = ping_indexnow(domain, url)
    receipt.update(state='published', httpStatus=200, verifiedAt=stamp(), publicPublicationVerified=True, indexNowPings=index_pings)
    write(folder / 'publication-receipt.json', receipt)
    return receipt

def publish_basic_article(domain, article, folder):
    from common.dashboard_jobs import write
    validate_basic_article(article)
    if article['category'] not in registered_categories(domain):
        raise ValueError('Category is not registered on this site')
    previous_path = folder / 'publication-receipt.json'
    previous = json.loads(previous_path.read_text()) if previous_path.is_file() else {}
    if previous.get('state') == 'published':
        return previous
    inventory = published_inventory('https://www.' + domain)
    collisions = duplicate_posts(article, inventory)
    if collisions:
        exact = [p for p in collisions if p.get('title', '').casefold() == article['title'].casefold()]
        if exact and previous.get('state') in ('accepted', 'submitting', 'submission_unknown'):
            response = requests.get(f"https://www.{domain}/api/posts/{exact[0]['id']}", timeout=15)
            return basic_public_receipt(domain, article, response, folder)
        if not exact:
            existing_slugs = {p.get('slug', '').casefold() for p in inventory}
            base_slug = article['topicSlug'][:160].rstrip('-')
            suffix = folder.parent.name.replace('-', '')[-4:] if re.fullmatch(r'\d{4}-\d{2}-\d{2}', folder.parent.name) else 'guide'
            candidate_slug = f"{base_slug}-{suffix}"
            seq = 2
            while candidate_slug.casefold() in existing_slugs:
                candidate_slug = f"{base_slug}-{suffix}-{seq}"
                seq += 1
            article['topicSlug'] = candidate_slug
            write(folder / 'article.json', article)
            write(folder / 'editor-content.json', article)
            collisions = duplicate_posts(article, inventory)
        if collisions:
            raise ValueError('Existing title or slug; duplicate submission prevented')
    if previous.get('state') in ('submitting', 'submission_unknown', 'accepted'):
        raise RuntimeError('Previous submission must be reconciled before a second POST')
    article = ensure_article_images(article, folder, domain=domain)
    from common.cf_tables import style_tables, inject_interactive_widget
    content = inject_interactive_widget(style_tables(article['contentHtml']), article.get('title', ''))
    plans = article.get('imagePlans', [])
    urls = []
    if plans:
        paths = [folder / 'images' / plan['filename'] for plan in plans]
        urls = upload_images_to_cf(domain, paths)
        for index, (plan, url) in enumerate(zip(plans, urls)):
            content = content.replace(f'{{{{IMAGE_{index}}}}}', url).replace('images/' + plan['filename'], url)
    if re.search('\\{\\{IMAGE|src=[\\"\\\'](?:images/|file:)', content):
        raise ValueError('Unresolved image reference')
    thumb_url = urls[0] if urls else ''
    payload = {
        'title': article['title'],
        'content': content,
        'slug': article['topicSlug'],
        'category': article['category'],
        'meta_description': article['summary'],
        'excerpt': article['summary'],
        'thumbnail': thumb_url,
        'og_image': thumb_url,
        'isPublished': True,
        'status': 'published',
    }
    key = get_api_key(domain)
    write(previous_path, {'state': 'submitting', 'domain': domain, 'title': article['title'], 'slug': article['topicSlug'], 'startedAt': stamp(), 'payloadSha256': hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()})
    try:
        response = requests.post(f'https://www.{domain}/api/posts', json=payload, headers={'x-api-key': key, 'Authorization': 'Bearer ' + key}, timeout=30)
    except requests.RequestException:
        write(previous_path, {'state': 'submission_unknown', 'domain': domain, 'title': article['title'], 'slug': article['topicSlug'], 'updatedAt': stamp()})
        raise
    if response.status_code not in (200, 201):
        write(previous_path, {'state': 'rejected', 'httpStatus': response.status_code, 'updatedAt': stamp()})
        raise RuntimeError('Publication API HTTP ' + str(response.status_code))
    return basic_public_receipt(domain, article, response, folder)


def slot_due(item, now):
    if item.get('status') == 'published':
        return False
    retry = item.get('nextRetryAt')
    if retry:
        try:
            retry_at = datetime.datetime.fromisoformat(retry.replace('Z','+00:00'))
            if retry_at.tzinfo is None: retry_at=retry_at.replace(tzinfo=KST)
            if retry_at > now: return False
        except ValueError:
            pass
    if item.get('status') in ('waiting','pending'):
        scheduled = item.get('scheduledTime') or ''
        if re.fullmatch(r'\d{2}:\d{2}',scheduled) and scheduled > now.strftime('%H:%M'):
            return False
    return True

def main():
    import argparse
    parser = argparse.ArgumentParser(description='CF one-pass posting')
    parser.add_argument('domains', nargs='*')
    parser.add_argument('--basic-article')
    parser.add_argument('--prepare-only', action='store_true')
    parser.add_argument('--catch-up-today-once', action='store_true')
    parser.add_argument('--catch-up-once', action='store_true')
    parser.add_argument('--manual-retry-once', action='store_true')
    parser.add_argument('--repair-failed-domain')
    parser.add_argument('--limit', type=int, default=16)
    args = parser.parse_args()
    schedule = load_current_schedule()
    domains = args.domains or ([args.repair_failed_domain] if args.repair_failed_domain else [])
    if not domains or domains == ['remaining']:
        today = datetime.datetime.now(KST).date().isoformat()
        if schedule.get('date') != today:
            raise ValueError('Current-day schedule required')
        domains = [row['domain'] for row in schedule.get('items', []) if slot_due(row, datetime.datetime.now(KST))][:args.limit]
    if any((domain not in ALL_DOMAINS for domain in domains)):
        parser.error('Unknown channel domain')
    if args.basic_article and len(domains) != 1:
        parser.error('--basic-article requires exactly one domain')
    with cleaner_lock() as acquired:
        if not acquired:
            print(json.dumps({'status': 'busy'}))
            return
        for domain in domains:
            try:
                run_basic_posting(domain, args.basic_article, args.prepare_only)
            except Exception as exc:
                schedule = json.loads(SCHEDULE_JSON.read_text(encoding='utf-8'))
                item = next((row for row in schedule['items'] if row['domain'] == domain))
                item.update(status='failed', lastError=type(exc).__name__ + ': ' + str(exc)[:400], nextRetryAt=(datetime.datetime.now(KST) + datetime.timedelta(minutes=5)).isoformat())
                save_schedule_file(SCHEDULE_JSON, schedule)
                print(json.dumps({'domain': domain, 'status': 'failed', 'errorType': type(exc).__name__}), flush=True)
                if len(domains) == 1:
                    raise

def save_live(path, content):
    from common.dashboard_jobs import atomic_text
    atomic_text(path, content)

@contextmanager
def cleaner_lock(path=None, wait_seconds=0, poll_interval=5):
    from common import runtime_locks as fcntl
    from common.runtime_locks import runtime_lock_path
    path = runtime_lock_path(path or DATA_DIR / 'cleaner.lock')
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+b') as handle:
        deadline = time.monotonic() + max(0, wait_seconds)
        while True:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    yield False
                    return
                time.sleep(min(poll_interval, deadline - time.monotonic()))
        try:
            yield True
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

def load_current_schedule():
    today = datetime.datetime.now(KST).date().isoformat()
    previous = json.loads(SCHEDULE_JSON.read_text(encoding='utf-8')) if SCHEDULE_JSON.exists() else {}
    if previous.get('date') == today:
        return previous
    if previous.get('date'):
        if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', previous['date']):
            raise ValueError('Invalid saved schedule date')
        archive = DATA_DIR / 'schedule_history' / (previous['date'] + '.json')
        if not archive.exists():
            save_schedule_file(archive, previous)
    old = {row['domain']: row for row in previous.get('items', [])}
    items = []
    for index, domain in enumerate(ALL_DOMAINS):
        prior = old.get(domain, {})
        item = {key: prior[key] for key in ('order','id','name','color','icon','category') if key in prior}
        item.update(domain=domain, order=index+1, id=prior.get('id', index+1),
                    scheduledTime=prior.get('scheduledTime', f'{9+(30+50*index)//60:02d}:{(30+50*index)%60:02d}'),
                    status='waiting')
        items.append(item)
    schedule = {'date': today, 'items': items}
    save_schedule_file(SCHEDULE_JSON, schedule)
    return schedule


def basic_progress(domain, stage, name, pct, detail, status='processing'):
    schedule = json.loads(SCHEDULE_JSON.read_text(encoding='utf-8'))
    row = next(item for item in schedule['items'] if item['domain'] == domain)
    row.update(currentStage=stage, stageName=name, progressPct=pct, detailMessage=detail, status=status)
    save_schedule_file(SCHEDULE_JSON, schedule)
    state = {'activeBlogId': row.get('id'), 'completedBlogIds': [i.get('id') for i in schedule['items'] if i.get('status')=='published'],
             'domain': domain, 'activeDomain': domain, 'blogName': row.get('name', domain),
             'category': row.get('category'), 'title': row.get('title', ''), 'summary': row.get('summary', ''),
             'currentStage': stage, 'stageName': name, 'progressPct': pct, 'detailMessage': detail,
             'status': status, 'updatedAt': datetime.datetime.now(KST).isoformat(), 'timestamp': int(time.time())}
    save_schedule_file(STATE_JSON, state)
    save_live(STATUS_JS, 'window.__PIPELINE_STATUS__ = '+json.dumps(state,ensure_ascii=False)+';\n')


def run_basic_posting(domain, artifact_folder=None, prepare_only=False):
    if not prepare_only and (Path.home() / 'EGO_EXEC_DISABLED').exists():
        raise RuntimeError('Execution paused by EGO_EXEC_DISABLED')
    from common.dashboard_jobs import write
    schedule = load_current_schedule()
    item = next((row for row in schedule.get('items', []) if row.get('domain') == domain), None)
    if not item: raise ValueError('Domain missing from current schedule')
    if item.get('status') == 'published' and item.get('publicUrl'):
        return {'status': 'already_published', 'state': 'published', 'publicPublicationVerified': True, 'httpStatus': 200, 'publicUrl': item['publicUrl'], 'title': item.get('title', domain), 'domain': domain}
    folder = Path(artifact_folder).resolve() if artifact_folder else BASE_DIR / item.get('artifactFolder', '')
    if not artifact_folder and not (folder / 'article.json').is_file():
        folder = BASE_DIR / 'output' / ('basic-' + domain + '-' + uuid.uuid4().hex[:10])
    if not folder.resolve().is_relative_to((BASE_DIR / 'output').resolve()):
        raise ValueError('Article folder must be inside channel output')
    folder.mkdir(parents=True, exist_ok=True)
    item.update(artifactFolder=str(folder.relative_to(BASE_DIR)), attemptStartedAt=stamp(),
                attemptCount=item.get('attemptCount', 0)+1, totalAttempts=item.get('totalAttempts', 0)+1)
    save_schedule_file(SCHEDULE_JSON, schedule)
    basic_progress(domain, 1, '키워드·주제', 10, '당일 슬롯과 보존 원고 확인')
    article = basic_article(domain, item, folder)
    if prepare_only: return {'status': 'prepared', 'folder': str(folder)}
    if datetime.datetime.now(KST).date().isoformat() != schedule['date']:
        raise RuntimeError('Work date changed before submission; saved article retained')
    basic_progress(domain, 6, '최종 발행', 90, '기본 형식 확인 · API 게시 및 공개 페이지 확인')
    receipt = publish_basic_article(domain, article, folder)
    schedule = json.loads(SCHEDULE_JSON.read_text(encoding='utf-8'))
    item = next(row for row in schedule['items'] if row.get('domain') == domain)
    item.update(status='published', publicUrl=receipt['publicUrl'], publicationDate=schedule['date'],
                publishedAt=receipt['verifiedAt'], completedAt=receipt['verifiedAt'],
                title=article['title'], slug=article['topicSlug'], lastExitCode=0)
    for key in ('lastError','nextRetryAt','editorialNextAt'):item.pop(key,None)
    save_schedule_file(SCHEDULE_JSON, schedule)
    basic_progress(domain,6,'발행 완료',100,'공개 HTTP 200 · '+receipt['publicUrl'],status='published')
    try:
        from dashboard.collectors.metrics import inventory as site_inventory, read_json, CONFIG
        from dashboard.collectors.indexing_submissions import submit_indexnow
        config = read_json(CONFIG)
        site = next(site for site in site_inventory() if site.get('site_id') == domain)
        write(folder / 'indexnow-receipt.json', submit_indexnow(site, config.get('sites', {}).get(domain, {}), [receipt['publicUrl']]))
    except Exception as exc:
        write(folder / 'indexnow-receipt.json', {'status': 'retry_wait', 'errorType': type(exc).__name__})
    print(json.dumps(receipt, ensure_ascii=False), flush=True)
    return receipt

if __name__ == '__main__':

    main()
