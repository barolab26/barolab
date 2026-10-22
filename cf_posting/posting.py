"""One-pass publishing: research, document, format checks, submit, verify."""

import sys
sys.dont_write_bytecode = True

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

sys.path.insert(0, str(BASE_DIR.parent))

import os

import time

import datetime

import json

import requests

import re

import hashlib

import mimetypes

from bs4 import BeautifulSoup

from pathlib import Path

from common.ego_telemetry import action as ego_action

from common.channel_attribution import is_dummy_rescue_url

import uuid

import os, time, hashlib, datetime

import argparse

from contextlib import contextmanager

BASE_DIR = Path(__file__).resolve().parent

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

def basic_article(domain, item, folder):
    path = folder / 'article.json'
    if path.is_file():
        handoff = folder / 'handoff.json'
        if handoff.is_file() and json.loads(handoff.read_text(encoding='utf-8')).get('domain') not in (None, domain):
            raise ValueError('Saved article belongs to another domain')
        return validate_basic_article(json.loads(path.read_text(encoding='utf-8')))
    keyword = item.get('mainKeyword') or item.get('title') or item.get('topic') or item.get('category') or domain
    basic_progress(domain,2,'리서치',25,str(keyword))
    sources = basic_research(keyword, folder)
    from common.llm_client import generate_json
    from common.dashboard_jobs import write
    schema = {'type': 'object', 'properties': {key: {'type': 'string'} for key in ('title', 'summary', 'category', 'topicSlug', 'contentHtml')}, 'required': ['title', 'summary', 'category', 'topicSlug', 'contentHtml'], 'additionalProperties': False}
    prompt = 'Write one useful Korean blog article. Return the supplied JSON schema. Use only facts supported by the actual research below; do not invent dates, numbers, quotations or experience. Use paragraphs, headings and a useful explanatory table instead of fabricated UI screenshots. contentHtml is article body only; topicSlug is lowercase ASCII words separated by hyphens. Retain the scheduled topic and select a registered category. No independent review or approval request.\n' + json.dumps({'domain': domain, 'topic': keyword, 'categories': registered_categories(domain), 'research': sources}, ensure_ascii=False)
    basic_progress(domain,4,'원고 작성',55,str(keyword))
    article = validate_basic_article(generate_json(prompt, agent_slot='cf_pipeline', response_schema=schema, audit_directory=folder / 'model-audit', timeout_seconds=600))
    write(path, article)
    write(folder / 'editor-content.json', article)
    write(folder / 'photo-plan.json', {'assets': [], 'medium': 'html-table'})
    return article

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
    receipt.update(state='published', httpStatus=200, verifiedAt=stamp(), publicPublicationVerified=True)
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
        if previous.get('state') in ('accepted', 'submitting', 'submission_unknown'):
            exact = [p for p in collisions if p['slug'] == article['topicSlug'] and p['title'] == article['title']]
            if len(exact) == 1:
                response = requests.get(f"https://www.{domain}/api/posts/{exact[0]['id']}", timeout=15)
                return basic_public_receipt(domain, article, response, folder)
        raise ValueError('Existing title or slug; duplicate submission prevented')
    if previous.get('state') in ('submitting', 'submission_unknown', 'accepted'):
        raise RuntimeError('Previous submission must be reconciled before a second POST')
    content = article['contentHtml']
    plans = article.get('imagePlans', [])
    if plans:
        paths = [folder / 'images' / plan['filename'] for plan in plans]
        urls = upload_images_to_cf(domain, paths)
        for index, (plan, url) in enumerate(zip(plans, urls)):
            content = content.replace(f'{{{{IMAGE_{index}}}}}', url).replace('images/' + plan['filename'], url)
    if re.search('\\{\\{IMAGE|src=[\\"\\\'](?:images/|file:)', content):
        raise ValueError('Unresolved image reference')
    payload = {'title': article['title'], 'content': content, 'slug': article['topicSlug'], 'category': article['category'], 'meta_description': article['summary'], 'excerpt': article['summary'], 'isPublished': True, 'status': 'published'}
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
    import fcntl
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
        return {'status': 'already_published', 'publicUrl': item['publicUrl']}
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
        from dashboard.indexing_submissions import submit_indexnow
        config = read_json(CONFIG)
        site = next(site for site in site_inventory() if site.get('site_id') == domain)
        write(folder / 'indexnow-receipt.json', submit_indexnow(site, config.get('sites', {}).get(domain, {}), [receipt['publicUrl']]))
    except Exception as exc:
        write(folder / 'indexnow-receipt.json', {'status': 'retry_wait', 'errorType': type(exc).__name__})
    print(json.dumps(receipt, ensure_ascii=False), flush=True)
    return receipt

if __name__ == '__main__':

    main()
