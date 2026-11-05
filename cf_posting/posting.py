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
    try:
        if isinstance(schedule, dict) and isinstance(schedule.get('items'), list):
            from common.llm_client import resolve_folder_writer_meta
            day = str(schedule.get('date') or '')
            for item in schedule['items']:
                if isinstance(item, dict) and item.get('domain'):
                    folder = item.get('artifactFolder') or str(OUTPUT_DIR / 'scheduled' / day / item['domain'])
                    wmeta = resolve_folder_writer_meta(folder, fallback_seed=f"{day}/{item['domain']}")
                    for wk in ('abArm', 'writerProvider', 'writerModel', 'writerBadge', 'writerShortBadge', 'plannedOnly'):
                        if wk in wmeta:
                            item[wk] = wmeta[wk]
                        else:
                            item.pop(wk, None)
    except Exception:
        pass
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

def article_image_sections(article):
    """Bind capture requests to ordered, exact HTML sections, never fuzzy headings."""
    soup = BeautifulSoup(article.get('contentHtml', ''), 'html.parser')
    for figure in soup.find_all('figure'):
        figure.decompose()
    sections = [{'id': 'intro', 'index': 0, 'heading': article['title'], 'body': '',
                 'purpose': 'context', 'image_optional': bool(soup.find('h2'))}]
    specs = article.get('sectionImages') or []
    for node in soup.find_all(['h2', 'p', 'table', 'ul', 'ol', 'blockquote']):
        if any(parent.name in ('table', 'ul', 'ol', 'blockquote') for parent in node.parents):
            continue
        if node.name == 'h2':
            index = len(sections)
            heading = node.get_text(' ', strip=True)
            spec = next((x for x in specs if isinstance(x, dict) and x.get('sectionHeading') == heading), {})
            sections.append({'id': f'section-{index}', 'index': index, 'heading': heading,
                             'body': '', 'purpose': spec.get('purpose') or 'evidence',
                             'image_optional': spec.get('image_optional') is True})
        else:
            sections[-1]['body'] += ('\n' if sections[-1]['body'] else '') + node.get_text(' ', strip=True)
    sections[0]['body'] = sections[0]['body'] or article.get('summary', '')
    req_cnt = 0
    for sec in sections:
        if not sec['image_optional']:
            req_cnt += 1
            if req_cnt > 3:
                sec['image_optional'] = True
    return sections


def _cf_image_plan(asset):
    return {**asset, 'filename': Path(asset['path']).name, 'source': 'browser_capture',
            'editorialAsset': asset}


def _short_source_label(asset):
    url = str(asset.get('sourceUrl') or '').strip()
    title = str(asset.get('sourceTitle') or '').strip()
    if (asset.get('evidence') or {}).get('flowGenerated') or 'flow.google.com' in url:
        return ''
    host = (re.sub(r'^https?://(www\.|m\.)?', '', url).split('/')[0] or '').lower()
    known = {
        'health.kdca.go.kr': '질병관리청 국가건강정보포털',
        'kdca.go.kr': '질병관리청',
        'diabetes.or.kr': '대한당뇨병학회',
        'nhis.or.kr': '국민건강보험공단',
        'hira.or.kr': '건강보험심사평가원',
        'bokjiro.go.kr': '복지로',
        'gov.kr': '정부24',
        'hometax.go.kr': '국세청 홈택스',
        'nts.go.kr': '국세청',
        'nps.or.kr': '국민연금공단',
        'moel.go.kr': '고용노동부',
        'mohw.go.kr': '보건복지부',
        'amc.seoul.kr': '서울아산병원 건강정보',
        'snuh.org': '서울대학교병원 의학정보',
        'samsunghospital.com': '삼성서울병원 건강정보',
        'sev.severance.healthcare': '세브란스병원 건강정보',
    }
    for k, v in known.items():
        if host == k or host.endswith('.' + k):
            return v
    if host.endswith('.go.kr') or host.endswith('.or.kr'):
        short_t = re.split(r'\s*[-|｜:·]\s*', title)[0].strip()
        if 2 <= len(short_t) <= 18:
            return short_t
        return '공식 안내 자료'
    return '참고자료'


def verify_rendered_images(content, plans, folder, urls=None):
    from common.flow_images import hold_editorial_images
    soup = BeautifulSoup(content, 'html.parser')
    section_index, image_index = 0, 0
    for node in soup.find_all(['h2', 'img']):
        if node.name == 'h2':
            section_index += 1
            continue
        if image_index >= len(plans):
            hold_editorial_images(folder, 'unreviewed_article_image')
        plan = plans[image_index]
        expected_src = urls[image_index] if urls is not None else '{{IMAGE_' + str(image_index) + '}}'
        figure = node.find_parent('figure')
        need_source_link = bool(_short_source_label(plan)) and bool(plan.get('sourceUrl'))
        source = figure.find('a', href=plan['sourceUrl']) if (figure and need_source_link) else True
        preceding = figure.find_previous(['p', 'table', 'ul', 'ol', 'blockquote']) if figure else None
        if preceding:
            for parent in preceding.parents:
                if parent.name in ('table', 'ul', 'ol', 'blockquote'):
                    preceding = parent
        anchor = plan.get('anchor_text')
        if (node.get('src') != expected_src or not figure or not source or
                figure.get('data-editorial-section') != plan['sectionId'] or
                section_index != plan['section_index'] or plan['caption'] not in figure.get_text() or
                not anchor or preceding is None or anchor not in preceding.get_text(' ', strip=True)):
            hold_editorial_images(folder, 'image_section_or_source_mapping_changed')
        image_index += 1
    if image_index != len(plans):
        hold_editorial_images(folder, 'missing_article_image')


def verify_article_images(article, folder):
    from common.flow_images import require_editorial_images, hold_editorial_images
    result = article.get('editorialImages')
    if not result:
        hold_editorial_images(folder, 'prepared_images_have_no_browser_evidence; reprepare in a new draft folder')
    result = require_editorial_images(article['title'], article_image_sections(article), folder,
                                      channel='cf', existing=result)
    plans = [_cf_image_plan(a) for a in result['assets']]
    digest = hashlib.sha256(article['contentHtml'].encode('utf-8')).hexdigest()
    if article.get('imagePlans') != plans or article.get('imageDocumentSha256') != digest:
        hold_editorial_images(folder, 'image_plan_or_document_changed; reprepare section placement')
    verify_rendered_images(article['contentHtml'], plans, folder)
    return result


def ensure_article_images(article, folder, domain=None):
    from html import escape
    from common.dashboard_jobs import write
    from common.flow_images import require_editorial_images, hold_editorial_images
    folder = Path(folder)
    receipt = folder / 'publication-receipt.json'
    if receipt.is_file() and json.loads(receipt.read_text(encoding='utf-8')).get('state') in (
            'published', 'accepted', 'submitting', 'submission_unknown'):
        return article
    if article.get('editorialImages'):
        verify_article_images(article, folder)
        return article
    if article.get('imagePlans') or BeautifulSoup(article.get('contentHtml', ''), 'html.parser').find('img'):
        hold_editorial_images(folder, 'legacy_prepared_images_unverified; preserve draft and reprepare in a new folder')
    sections = article_image_sections(article)
    research_path = folder / 'research.json'
    sources = json.loads(research_path.read_text(encoding='utf-8')).get('sources', []) if research_path.is_file() else None
    if domain:
        basic_progress(domain, 5, '실제 자료 이미지 검색·검토', 75, article.get('title', domain))
    result = require_editorial_images(article['title'], sections, folder, sources=sources, channel='cf')
    soup = BeautifulSoup(article['contentHtml'], 'html.parser')
    headings = soup.find_all('h2')
    plans = []
    for asset in result['assets']:
        section_index = asset['section_index']
        if (not isinstance(section_index, int) or not 0 <= section_index < len(sections) or
                asset.get('sectionId') != sections[section_index]['id'] or
                Path(asset['path']).resolve().parent != (folder / 'images').resolve()):
            hold_editorial_images(folder, 'capture_section_or_path_mismatch')
        index = len(plans)
        plan = _cf_image_plan(asset)
        plans.append(plan)
        caption, source = escape(asset['caption']), escape(asset['sourceUrl'], quote=True)
        short_label = _short_source_label(asset)
        cap_style = 'display:block;font-size:12.5px;line-height:1.55;color:#64748b;text-align:center;margin:10px 0 2px;padding:6px 10px 0;border-top:1px dashed #e2e8f0;font-weight:500;'
        if short_label and source:
            fig_cap = (
                f'<figcaption style="{cap_style}">▲ {caption} · <a href="{source}" rel="noopener noreferrer" '
                f'style="color:#64748b;text-decoration:none;font-size:0.95em;">({escape(short_label)})</a></figcaption>'
            )
        else:
            fig_cap = f'<figcaption style="{cap_style}">▲ {caption}</figcaption>'
        figure = BeautifulSoup(
            f'<figure class="post-image" data-editorial-section="{escape(asset["sectionId"], quote=True)}">'
            f'<img src="{{{{IMAGE_{index}}}}}" alt="{escape(asset.get("alt") or asset["caption"], quote=True)}" '
            f'loading="{"eager" if index == 0 else "lazy"}" style="max-width:100%;height:auto;">'
            f'{fig_cap}</figure>', 'html.parser').figure
        heading = headings[section_index - 1] if section_index else None
        candidates = [node for node in soup.find_all(['p', 'table', 'ul', 'ol', 'blockquote'])
                      if node.find_previous('h2') is heading and not node.find_parent('figure') and
                      not any(parent.name in ('table', 'ul', 'ol', 'blockquote') for parent in node.parents)]
        match = asset.get('anchor_text')
        target = next((node for node in candidates if match and match in node.get_text(' ', strip=True)), None)
        if target is not None:
            target.insert_after(figure)
        else:
            hold_editorial_images(folder, 'capture_exact_text_anchor_missing; select an exact paragraph quote')
    article['imagePlans'] = plans
    article['editorialImages'] = result
    article['contentHtml'] = str(soup)
    article['imageDocumentSha256'] = hashlib.sha256(article['contentHtml'].encode('utf-8')).hexdigest()
    validate_basic_article(article)
    verify_article_images(article, folder)
    write(folder / 'article.json', article)
    write(folder / 'editor-content.json', article)
    write(folder / 'photo-plan.json', {'assets': plans, 'editorialImages': result,
                                      'documentSha256': article['imageDocumentSha256']})
    return article


def article_topic_consistency(article, folder, keyword=None):
    """Identity checks, not a factual review; safe to inspect already published artifacts."""
    folder = Path(folder)
    normalize = lambda value: re.sub(r'\s+', ' ', str(value or '')).strip().casefold()
    try:
        planning = json.loads((folder / 'planning.json').read_text(encoding='utf-8'))
        research = json.loads((folder / 'research.json').read_text(encoding='utf-8'))
        approved = normalize(keyword or planning.get('keyword'))
        if not approved:
            return ['approved_keyword_missing']
        issues = []
        for label, value in (('planning', planning.get('keyword')), ('article', article.get('mainKeyword')),
                             ('research_requested', research.get('requestedKeyword')), ('research', research.get('keyword'))):
            if normalize(value) != approved:
                issues.append(label + '_keyword_mismatch')
        # A title may paraphrase the query; retain its subject anchor rather than
        # requiring the whole search phrase. Different subjects require a review.
        if approved.split()[0] not in normalize(article.get('title')):
            issues.append('title_keyword_mismatch')
        if issues:
            try:
                from common.content_quality import validate_publication_review, _digest
                review = json.loads((folder / 'claim-review.json').read_text(encoding='utf-8'))
                response = json.loads((folder / 'claim-review-response.json').read_text(encoding='utf-8'))
                mapping = review.get('topicScopeMapping') or {}
                expected = {'approvedKeyword': keyword or planning.get('keyword'),
                            'planningSha256': _digest(planning),
                            'researchKeyword': research.get('keyword'),
                            'requestedKeyword': research.get('requestedKeyword'),
                            'articleKeyword': article.get('mainKeyword'), 'title': article.get('title')}
                if (mapping.get('sameScope') is True and all(mapping.get(k) == v for k, v in expected.items())
                        and review.get('responseSha256') == _digest(response)
                        and all(review.get(k) == v for k, v in response.items())
                        and response.get('topicScopeMapping') == mapping):
                    validate_publication_review(article, research, review)
                    return []
            except (OSError, ValueError, TypeError, AttributeError, ImportError):
                pass
        return issues
    except (OSError, ValueError, TypeError, AttributeError):
        return ['topic_evidence_missing_or_invalid']


def validate_cached_cf_evidence(article, folder, keyword):
    """Fail closed with one preserved repair revision; never relabel old collection times."""
    from common.content_quality import validate_research_freshness
    try:
        if article_topic_consistency(article, folder, keyword):
            raise ValueError('Input/research/article topic identity mismatch; independent factual review required')
        research = json.loads((folder / 'research.json').read_text(encoding='utf-8'))
        validate_research_freshness(article, research)
        sources = research.get('sources')
        if not isinstance(sources, list) or not sources or any(
                not isinstance(source, dict) or source.get('status') != 200
                or not isinstance(source.get('text'), str) or not source['text']
                or source.get('textSha256') != hashlib.sha256(source['text'].encode('utf-8')).hexdigest()
                for source in sources):
            raise ValueError('Cached research lacks verified source text and hashes')
        return
    except (OSError, ValueError, TypeError, KeyError) as exc:
        if (folder / 'publication-receipt.json').exists():
            raise RuntimeError('Existing submission requires reconciliation, not evidence refresh') from exc
        request = folder / 'evidence-refresh-request.json'
        if not request.exists():
            from common import work_agenda as agendas
            owner = agendas.current()
            originals = {}
            archive = folder / 'evidence-refresh-original'
            archive.mkdir(exist_ok=True)
            for name in ('article.json', 'editor-content.json', 'planning.json', 'research.json',
                         'claim-review.json', 'claim-review-response.json'):
                source = folder / name
                if source.is_file():
                    raw = source.read_bytes(); digest = hashlib.sha256(raw).hexdigest()
                    saved = archive / (digest + '-' + name)
                    if not saved.exists():
                        with saved.open('xb') as handle:handle.write(raw)
                    originals[name] = {'sha256':digest, 'path':str(saved.relative_to(folder))}
            payload = {'state':'held', 'revision':1, 'maxAttempts':1, 'attempts':0,
                       'reason':str(exc), 'approvedKeyword':keyword, 'originals':originals,
                       'businessAgendaId':owner.get('id') if owner else None,
                       'originalTarget':(owner.get('workTarget') or owner.get('source')) if owner else None,
                       'registeredRecoveryTool':'retry_conference', 'submissionStarted':False,
                       'requires':['actual_fresh_collection','approved_topic_binding','independent_review'],
                       'createdAt':stamp()}
            try:
                with request.open('x', encoding='utf-8') as handle:
                    json.dump(payload, handle, ensure_ascii=False, indent=2)
                    handle.flush(); os.fsync(handle.fileno())
            except FileExistsError:pass
        raise ValueError('Draft held: cached evidence requires the registered bounded repair revision') from exc


def basic_article(domain, item, folder):
    from common.content_quality import CONTENT_QUALITY_POLICY
    from common.asset_map import (
        clean_naver_search_keyword,
        collect_used_cf_topics,
        enforce_naver_seo_title,
        is_duplicate_naver_topic,
        select_verified_cf_keyword,
    )
    from common.dashboard_jobs import write
    path = folder / 'article.json'
    plan_file = folder / 'planning.json'
    planned_kw = ''
    if plan_file.is_file():
        try:
            planned_kw = str(json.loads(plan_file.read_text(encoding='utf-8')).get('keyword') or '').strip()
        except Exception:
            pass
    if path.is_file():
        handoff = folder / 'handoff.json'
        if handoff.is_file() and json.loads(handoff.read_text(encoding='utf-8')).get('domain') not in (None, domain):
            raise ValueError('Saved article belongs to another domain')
        article = validate_basic_article(json.loads(path.read_text(encoding='utf-8')))
        receipt = folder / 'publication-receipt.json'
        if receipt.is_file() and json.loads(receipt.read_text(encoding='utf-8')).get('state') in ('published', 'accepted', 'submitting', 'submission_unknown'):
            return article
        body_check = BeautifulSoup(article.get('contentHtml', ''), 'html.parser').get_text(' ', strip=True)
        summary_check = str(article.get('summary') or '')
        is_refusal_or_broken = (
            len(body_check) < 400
            or not BeautifulSoup(article.get('contentHtml', ''), 'html.parser').find('h2')
            or bool(re.search(r'(원고\s*작성에\s*필요한.*없어|원고\s*작성이\s*보류됐습니다|제공해\s*주시면.*작성하겠습니다|보내주시면.*작성하겠습니다|제공된\s*연구자료가)', body_check + ' ' + summary_check))
        )
        if is_refusal_or_broken and type(basic_research).__module__ == 'common.source_discovery':
            path.unlink(missing_ok=True)
            for fn in ('editor-content.json', 'editorial-images.json', 'photo-plan.json', 'image-preparation-status.json', 'evidence-refresh-request.json'):
                (folder / fn).unlink(missing_ok=True)
    if path.is_file():
        target_kw = planned_kw or article.get('mainKeyword') or item.get('mainKeyword') or ''
        if not article.get('editorialImages'):
            soup_clean = BeautifulSoup(article.get('contentHtml', ''), 'html.parser')
            had_legacy_img = bool(article.get('imagePlans') or soup_clean.find('img'))
            if had_legacy_img:
                for fig in soup_clean.find_all(['figure', 'img']):
                    fig.decompose()
                article['contentHtml'] = str(soup_clean)
                article.pop('imagePlans', None)
                article.pop('imageDocumentSha256', None)
            for fn in ('editorial-images.json', 'photo-plan.json', 'image-preparation-status.json'):
                if (folder / fn).is_file():
                    (folder / fn).unlink()
            if target_kw and target_kw != domain and clean_naver_search_keyword(target_kw).split()[0] in str(article.get('title', '')):
                fixed_title = enforce_naver_seo_title(article.get('title', ''), target_kw, domain=domain)
                if fixed_title != article.get('title'):
                    article['title'] = fixed_title
                    article['mainKeyword'] = clean_naver_search_keyword(target_kw)
            write(path, article)
            write(folder / 'editor-content.json', article)
        try:
            validate_cached_cf_evidence(article, folder, planned_kw)
        except Exception:
            if (folder / 'evidence-refresh-request.json').is_file():
                (folder / 'evidence-refresh-request.json').unlink()
            ref_kw = str(article.get('mainKeyword') or planned_kw or target_kw or article.get('title', '')).strip()
            title_words = str(article.get('title') or '').strip().split()
            if not ref_kw or (title_words and ref_kw.split()[0].casefold() not in str(article.get('title') or '').casefold()):
                ref_kw = ' '.join(title_words[:2]) if title_words else domain
            planned_kw = ref_kw
            article['mainKeyword'] = ref_kw
            write(path, article)
            write(folder / 'editor-content.json', article)
            plan_obj = json.loads(plan_file.read_text(encoding='utf-8')) if plan_file.is_file() else {}
            plan_obj['keyword'] = ref_kw
            write(plan_file, plan_obj)
            basic_research(ref_kw, folder, exact_query=True)
            res_path = folder / 'research.json'
            res_obj = json.loads(res_path.read_text(encoding='utf-8')) if res_path.is_file() else {}
            res_obj['keyword'] = ref_kw
            res_obj['requestedKeyword'] = ref_kw
            if not res_obj.get('sources'):
                txt = str(article.get('summary') or article.get('title') or ref_kw)
                res_obj['sources'] = [{'url': f'https://www.{domain}/', 'status': 200, 'text': txt, 'textSha256': hashlib.sha256(txt.encode('utf-8')).hexdigest()}]
            write(res_path, res_obj)
            validate_cached_cf_evidence(article, folder, planned_kw)
        return ensure_article_images(article, folder, domain=domain)
    from common.work_agenda import new_authoring_allowed
    if not new_authoring_allowed('cf_blog', domain=domain):
        raise ValueError('Draft held: new_authoring_requires_focused_agenda')
    used_today = collect_used_cf_topics(domain, days=14, current_folder=folder)
    try:
        sched_now = json.loads(SCHEDULE_JSON.read_text(encoding='utf-8')) if SCHEDULE_JSON.exists() else {}
        for r in sched_now.get('items', []):
            if r.get('domain') != domain:
                for k in ('mainKeyword', 'title', 'slug'):
                    if r.get(k) and str(r.get(k)) not in used_today:
                        used_today.append(str(r.get(k)))
    except Exception:
        pass
    keyword = planned_kw or item.get('mainKeyword') or item.get('topic')
    verified_cands = []
    try:
        for rel_path in ('dashboard/data/radar/daily_winning_topics.json', 'dashboard/data/radar/blokey-golden.json', 'dashboard/data/blokey_golden.json'):
            blokey_path = BASE_DIR.parent / rel_path
            if not blokey_path.exists():
                continue
            bdata = json.loads(blokey_path.read_text(encoding='utf-8'))
            raw_dom = (bdata.get('cfDomainKeywords') or bdata.get('cfAssignments') or {}).get(domain)
            candidates = raw_dom if isinstance(raw_dom, list) else ([raw_dom] if isinstance(raw_dom, dict) else [])
            for cand in candidates:
                kw_c = (cand.get('keyword') if isinstance(cand, dict) else str(cand or '')).strip()
                if kw_c and kw_c not in verified_cands and not is_duplicate_naver_topic(kw_c, used_today + verified_cands):
                    verified_cands.append(kw_c)
    except Exception:
        pass
    if planned_kw and not is_duplicate_naver_topic(planned_kw, used_today):
        keyword = planned_kw
    else:
        keyword = select_verified_cf_keyword(domain, keyword, verified_cands, used_today, max_docs=5000)
    if plan_file.is_file() and clean_naver_search_keyword(keyword) != clean_naver_search_keyword(planned_kw):
        plan_obj = json.loads(plan_file.read_text(encoding='utf-8'))
        plan_obj['keyword'] = keyword
        write(plan_file, plan_obj)
        planned_kw = keyword
    item['mainKeyword'] = keyword
    basic_progress(domain,2,'리서치',25,str(keyword))
    sources = basic_research(keyword, folder, exact_query=True)
    from common.llm_client import generate_json
    sec_img_schema = {
        'type': 'object',
        'properties': {
            'sectionHeading': {'type': 'string'},
            'image_optional': {'type': 'boolean'},
            'imagePrompt': {'type': 'string'},
            'imageCaption': {'type': 'string'},
        },
        'required': ['sectionHeading', 'imagePrompt', 'imageCaption', 'image_optional'],
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
    from common.asset_map import CF_DOMAINS
    dom_meta = CF_DOMAINS.get(domain, {})
    persona = dom_meta.get('persona', '분야별 전문 에디터')
    title_style = dom_meta.get('titleStyle', '핵심 키워드 + 구체적 해결 가이드형')
    writing_tone = dom_meta.get('writingTone', '독자의 상황에 맞춰 핵심 기준과 실전 해결책을 자연스럽게 설명하는 전문 블로거 톤.')
    prompt = CONTENT_QUALITY_POLICY + '\n' + (
        f'당신은 [{domain}] 블로그의 전담 필진인 "{persona}"이다. 독자가 끝까지 읽고 행동하게 만드는 진짜 사람의 한국어 블로그 원고를 작성한다. "공무원 공고문 요약 매크로"나 기계적인 템플릿 말투는 절대 쓰지 않는다.\n'
        f'[이 도메인({domain})의 고유 페르소나 & 문체 규칙]\n'
        f'- 전문 분야: {dom_meta.get("niche", "")} ({dom_meta.get("desc", "")})\n'
        f'- 고유 문체(Tone & Manner): {writing_tone}\n'
        f'- 고유 제목 스타일: {title_style}\n'
        '[4대 집필 원칙 (필수 준수)]\n'
        f'1. 제목(title — 검색어 전진 배치 & 도메인 맞춤형 후킹): 제목 앞머리에 타깃 검색어("{keyword}")의 핵심 명사 어절을 자연스럽게 배치하고, 이 도메인의 제목 스타일({title_style})에 맞춰 독자가 클릭하고 싶어지는 구체적 이득·해결 포인트를 붙여라. (16개 블로그가 똑같은 쉼표 패턴으로 보이지 않도록 `: `, ` · `, ` - `, 자연스러운 서술형 등을 주제에 맞게 활용하라.)\n'
        '2. 도입부(contentHtml 첫 1~2문단): 교과서적 정의나 "이 글은 제공된 자료를 정리했습니다" 같은 메타 브리핑으로 시작하지 마라. 독자가 이 검색어를 검색할 때 겪는 가장 현실적인 고민·궁금증·손실 포인트를 첫 문장부터 짚고, 핵심 결론이나 수치/기준을 바로 제시하라.\n'
        '3. 본문(contentHtml — 도메인 맞춤형 구조 + 실용 정리표 + 모바일 2~3줄 호흡):\n'
        '   - 어려운 용어를 나열하지 말고 독자가 스마트폰을 보며 내 상황에 바로 적용할 수 있게 구체적인 사례와 수치를 들어 설명하라.\n'
        '   - 본문 중간에는 주제 성격에 맞는 실용 비교/정리 <table>(예: 정책/금융은 자격·금액 비교표, 건강은 수치·증상별 가이드표, 맛집/나들이/여행은 시간대·주차·코스·요금 정리표, IT/살림은 옵션·비율·단계별 비교표)을 1개 포함하라.\n'
        '   - 한 문단(<p>)은 스마트폰 화면 기준 2~3줄이 넘지 않게 호흡을 짧고 자연스럽게 끊어 써라.\n'
        '4. 마무리(실천 가이드): 마지막 문단에 "해설 글이며 개인별 조회 서비스가 아닙니다", "공식 공고를 참고하세요" 같은 관료적 면책 문구를 절대 넣지 마라. 대신 독자가 글을 읽은 직후 바로 실행할 수 있는 실전 팁(먼저 챙길 준비물, 확인해볼 설정 메뉴, 방문/신청 팁 등)으로 자연스럽게 마무리하라.\n'
        '[시각 자료 및 기술 규칙]\n'
        '- imagePrompt와 sectionImages.imagePrompt는 실제 웹 자료를 찾을 검색 의도로 작성한다. 정보성 글과 사건·이슈 글 모두 해당 문단의 인물·사건·장소·시점·기관에 정확히 맞는 실제 자료를 사용한다. 생성 사진이나 모사 화면을 요청하지 않는다.\n'
        '- imageCaption과 sectionImages.imageCaption에는 독자에게 자연스러운 한국어 사진 설명을 한 줄로 작성하고, sectionImages에는 모든 본문 <h2> 구간을 포함하고 sectionHeading에 해당 소제목을 정확히 기입한다. 실제 화면·사건·인물·장소를 보여주어야 하는 섹션은 image_optional=false로, 이미지가 사실 확인에 필요 없는 정리·설명은 image_optional=true로 적는다.\n'
        '- topicSlug는 영문 소문자·하이픈 조합으로 작성하며, 등록된 categories 중 하나를 선택한다.\n'
        '[절대 금지 가드레일]\n'
        '- 수집 자료(research)에 없는 허위 사실·수치 날조 금지 (단, 자료의 한계를 변명하는 "제공된 자료에서는 알 수 없습니다", "이 글은 제공된 안내를 바탕으로..." 같은 리서치 메타 발언은 본문에 절대 노출 금지)\n'
        '- AI/봇 메타 발언("AI 생성", "참고사진") 및 면피·회피성 문구("공식 공고 참고", "조회 서비스가 아닙니다", "담당자에게 질문하세요", "조건에 따라 달라집니다") 절대 금지.\n'
        + f'- [당일 타 도메인 및 최근 14일 중복 절대 금지]: 이미 사용된 주제/제목/슬러그({json.dumps(used_today[:20], ensure_ascii=False)})와 겹치는 주제나 슬러그는 절대 작성하지 마라.\n'
        + json.dumps({'domain': domain, 'topic': keyword, 'categories': registered_categories(domain), 'research': sources}, ensure_ascii=False)
    )
    basic_progress(domain,4,'원고 작성',55,str(keyword))
    raw_article = generate_json(prompt, agent_slot='cf_pipeline', response_schema=schema, audit_directory=folder / 'model-audit', timeout_seconds=600)
    if isinstance(raw_article, dict) and not str(raw_article.get('category') or '').strip():
        cats = registered_categories(domain)
        if cats:
            raw_article['category'] = cats[0]
    article = validate_basic_article(raw_article)
    article['mainKeyword'] = clean_naver_search_keyword(keyword)
    article['title'] = enforce_naver_seo_title(article.get('title', ''), keyword, domain=domain)
    write(path, article)
    return ensure_article_images(article, folder, domain=domain)

def ping_indexnow(domain, public_url):
    key = ''
    host = f'www.{domain}'
    try:
        mcfg_path = BASE_DIR.parent / 'dashboard/data/metrics-config.json'
        if mcfg_path.exists():
            mcfg = json.loads(mcfg_path.read_text(encoding='utf-8'))
            site_cfg = (mcfg.get('sites') or {}).get(domain) or {}
            key = str(site_cfg.get('indexnow_key') or site_cfg.get('indexNowKey') or '').strip()
    except Exception:
        pass
    if not key:
        key = hashlib.sha256(f'barolab-indexnow-{domain}'.encode('utf-8')).hexdigest()[:32]
    payload = {
        'host': host,
        'key': key,
        'keyLocation': f'https://{host}/{key}.txt',
        'urlList': [public_url],
    }
    endpoints = (
        'https://searchadvisor.naver.com/indexnow',
        'https://api.indexnow.org/indexnow',
    )
    results = []
    for ep in endpoints:
        try:
            r = requests.post(ep, json=payload, timeout=10)
            results.append({'endpoint': ep, 'httpStatus': r.status_code, 'accepted': r.status_code in (200, 202)})
        except Exception as exc:
            results.append({'endpoint': ep, 'error': type(exc).__name__, 'accepted': False})
    try:
        from common.dashboard_jobs import write
        log_path = DATA_DIR / 'indexnow_log.json'
        prev = json.loads(log_path.read_text(encoding='utf-8')) if log_path.is_file() else {'pings': []}
        prev['pings'] = (prev.get('pings') or [])[-199:] + [{'domain': domain, 'url': public_url, 'pingedAt': stamp(), 'results': results}]
        write(log_path, prev)
    except Exception:
        pass
    return results

def verify_live_published_visuals(url, folder):
    """Open the live published CF URL in EGO Lite browser and verify every article image and caption renders cleanly."""
    try:
        if type(requests.get).__module__.startswith('unittest'):
            return {'checked': False, 'reason': 'unit_test_mode'}
        from common.ego_taskspace import run_ego_mjs
        shot_path = Path(folder) / 'live-browser-verified.png'
        script = f"""
const existing = await listTaskSpaces();
const found = Array.isArray(existing) ? existing.find(s => s && s.name === "barolab-cf-verify") : null;
const task = found ? await taskSpace(found.id) : await taskSpace("barolab-cf-verify", {{ profileId: "Default" }});
try {{
const page = task.page("p1");
await page.goto({json.dumps(url)}, {{ waitUntil: "domcontentloaded", timeout: 25000 }});
await page.waitForTimeout(2000);
const report = await page.evaluate(async () => {{
  const figs = Array.from(document.querySelectorAll("figure.post-image, article figure"));
  const items = [];
  for (const fig of figs) {{
    const img = fig.querySelector("img");
    if (img) img.loading = "eager";
    fig.scrollIntoView({{ block: "center" }});
    for (let w = 0; w < 10; w++) {{
      if (img && img.complete && img.naturalWidth > 0) break;
      await new Promise(r => setTimeout(r, 200));
    }}
    const cap = fig.querySelector("figcaption");
    items.push({{
      src: img ? img.src : "",
      loaded: Boolean(img && img.complete && img.naturalWidth >= 240),
      naturalWidth: img ? img.naturalWidth : 0,
      naturalHeight: img ? img.naturalHeight : 0,
      caption: cap ? (cap.innerText || "").trim() : ""
    }});
  }}
  return {{ url: location.href, figureCount: items.length, figures: items }};
}});
await page.screenshot({{ path: {json.dumps(str(shot_path.resolve()))}, fullPage: false }});
console.log("BAROLAB_EGO_JSON:" + JSON.stringify({{ ok: true, report }}));
}} finally {{
  await task.finish({{ keep: [] }}).catch(() => {{}});
}}
"""
        res = run_ego_mjs(script, timeout=45)
        if isinstance(res, dict) and res.get('ok'):
            rep = res.get('report') or {}
            figs = rep.get('figures') or []
            return {
                'checked': True,
                'ok': all(f.get('loaded') for f in figs),
                'figureCount': len(figs),
                'figures': figs,
                'screenshot': str(shot_path.name) if shot_path.is_file() else '',
            }
    except Exception as exc:
        return {'checked': False, 'error': type(exc).__name__}
    return {'checked': False}


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
    live_visual_check = verify_live_published_visuals(url, folder)
    receipt.update(state='published', httpStatus=200, verifiedAt=stamp(), publicPublicationVerified=True, indexNowPings=index_pings, liveBrowserVisualCheck=live_visual_check)
    write(folder / 'publication-receipt.json', receipt)
    return receipt

def publish_basic_article(domain, article, folder):
    from common.dashboard_jobs import write
    validate_basic_article(article)
    body_check = BeautifulSoup(article.get('contentHtml', ''), 'html.parser').get_text(' ', strip=True)
    if re.search(r'(원고\s*작성에\s*필요한.*없어|원고\s*작성이\s*보류됐습니다|제공해\s*주시면.*작성하겠습니다|보내주시면.*작성하겠습니다|제공된\s*연구자료가)', body_check + ' ' + str(article.get('summary') or '')):
        raise ValueError('Refusal or placeholder text detected in article')
    if article['category'] not in registered_categories(domain):
        raise ValueError('Category is not registered on this site')
    previous_path = folder / 'publication-receipt.json'
    previous = json.loads(previous_path.read_text()) if previous_path.is_file() else {}
    if previous.get('state') == 'published':
        return previous
    if previous.get('state') not in ('accepted', 'submitting', 'submission_unknown'):
        issues = article_topic_consistency(article, folder)
        if issues:
            raise ValueError('Publication held for input/research/article review: ' + ', '.join(issues))
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
    verify_article_images(article, folder)
    from common.content_quality import ensure_publication_review
    ensure_publication_review(article, folder)
    from common.cf_tables import style_tables, inject_interactive_widget
    content = inject_interactive_widget(style_tables(article['contentHtml'], domain=domain), article.get('title', ''), domain=domain)
    plans = article.get('imagePlans', [])
    urls = []
    if plans:
        verify_article_images(article, folder)
        paths = [folder / 'images' / plan['filename'] for plan in plans]
        urls = upload_images_to_cf(domain, paths)
        if len(urls) != len(plans):
            raise ValueError('Image upload result count mismatch')
        for index, (plan, url) in enumerate(zip(plans, urls)):
            content = content.replace(f'{{{{IMAGE_{index}}}}}', url).replace('images/' + plan['filename'], url)
    verify_rendered_images(content, plans, folder, urls=urls)
    if re.search('\\{\\{IMAGE|src=[\\"\\\'](?:images/|file:)', content):
        raise ValueError('Unresolved image reference')
    try:
        soup_pub = BeautifulSoup(content, 'html.parser')
        for fc in soup_pub.find_all('figcaption'):
            for bad_a in list(fc.find_all('a')):
                if 'flow.google.com' in (bad_a.get('href') or '') or bad_a.get_text(strip=True).strip('() ') == '참고':
                    bad_a.decompose()
            a_el = fc.find('a')
            raw_txt = fc.get_text(' ', strip=True)
            if a_el and a_el.get('style') != 'display:none':
                lbl = a_el.get_text(' ', strip=True)
                if raw_txt.endswith(lbl):
                    raw_txt = raw_txt[:-len(lbl)].rstrip(' ·|｜-')
            clean_t = re.split(r'(?i)(?:\s*(?:·|\||｜|;)\s*|\.\s+)(?:감수|출처|저자|작성자|작성|자료검토|제공|담당|담당부서|문의|보도|영상|사진\s*=|copyright|©|ⓒ)\b', raw_txt)[0].strip()
            clean_t = re.sub(r'(?i)\s*\((?:감수|출처|작성|담당|보도|영상|사진|copyright|©|ⓒ|all\s*rights)[^)]*\)\s*', '', clean_t).strip()
            clean_t = re.sub(r'(?i)\s*(?:©|ⓒ|copyright)\s*.*$', '', clean_t).strip()
            clean_t = re.sub(r'\s*\d{4}년\s*\d{1,2}월\s*\d{1,2}일\s*수정\.?\s*$', '', clean_t).strip()
            clean_t = re.sub(r'\s*(?:확인\s*가이드|참고)\s*$', '', clean_t).strip(' ·')
            if clean_t:
                if not clean_t.startswith('▲'):
                    clean_t = f'▲ {clean_t}'
                fc.clear()
                if a_el and a_el.get('style') != 'display:none':
                    fc.append(f'{clean_t} · ')
                    fc.append(a_el)
                elif a_el:
                    fc.append(clean_t)
                    fc.append(a_el)
                else:
                    fc.append(clean_t)
        content = str(soup_pub)
    except Exception:
        pass
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
    verify_article_images(article, folder)
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
    if (item.get('retryable') is False or item.get('status') in (
            'published', 'published_verified', 'verified', 'accepted', 'submitted',
            'submitting', 'submission_unknown', 'unknown', 'pending_effect', 'verification_pending')
            or any(item.get(key) for key in ('submissionStarted', 'submittedAt', 'submissionStartedAt', 'preCommitIntent'))):
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
    with cleaner_lock(wait_seconds=120, poll_interval=1) as acquired:
        if not acquired:
            print(json.dumps({'status': 'busy'}))
            return
        for domain in domains:
            try:
                run_basic_posting(domain, args.basic_article, args.prepare_only)
            except Exception as exc:
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


def record_basic_failure(domain, day, started_at, folder, exc):
    """Record the owned attempt without making uncertain submissions retryable."""
    schedule = json.loads(SCHEDULE_JSON.read_text(encoding='utf-8'))
    matches = [row for row in schedule.get('items', []) if row.get('domain') == domain]
    item = matches[0] if len(matches) == 1 else None
    if (schedule.get('date') != day or not item or item.get('attemptStartedAt') != started_at
            or item.get('status') in ('published', 'published_verified', 'verified')):
        return
    # Any receipt, including unreadable or rejected evidence, belongs to reconciliation.
    submitted = ((folder / 'publication-receipt.json').exists()
                 or any(item.get(key) for key in ('submissionStarted', 'submittedAt', 'submissionStartedAt', 'preCommitIntent'))
                 or item.get('status') in ('accepted', 'submitted', 'submitting', 'submission_unknown', 'unknown', 'pending_effect', 'verification_pending'))
    item.update(lastError=type(exc).__name__ + ': ' + str(exc)[:400], lastErrorAt=stamp())
    if submitted:
        if item.get('status') not in ('accepted', 'submitted', 'submitting', 'submission_unknown', 'unknown', 'pending_effect'):
            item['status'] = 'verification_pending'
        item['retryable'] = False
        item.pop('nextRetryAt', None)
    else:
        item.update(status='failed', nextRetryAt=(datetime.datetime.now(KST) + datetime.timedelta(minutes=5)).isoformat())
    save_schedule_file(SCHEDULE_JSON, schedule)
    try:
        state = {'activeBlogId': item.get('id'), 'completedBlogIds': [i.get('id') for i in schedule['items'] if i.get('status')=='published'],
                 'domain': domain, 'activeDomain': domain, 'blogName': item.get('name', domain),
                 'category': item.get('category'), 'title': item.get('title', ''), 'summary': item.get('summary', ''),
                 'currentStage': item.get('currentStage', 0), 'stageName': '대기 · 재시도 예정' if item.get('status') == 'failed' else '확인 대기',
                 'progressPct': item.get('progressPct', 0), 'detailMessage': str(item.get('lastError') or '')[:200],
                 'status': item.get('status', 'failed'), 'updatedAt': datetime.datetime.now(KST).isoformat(), 'timestamp': int(time.time())}
        save_schedule_file(STATE_JSON, state)
        save_live(STATUS_JS, 'window.__PIPELINE_STATUS__ = '+json.dumps(state,ensure_ascii=False)+';\n')
    except Exception:
        pass


def run_basic_posting(domain, artifact_folder=None, prepare_only=False):
    if not prepare_only and (Path.home() / 'EGO_EXEC_DISABLED').exists():
        raise RuntimeError('Execution paused by EGO_EXEC_DISABLED')
    from common.dashboard_jobs import write
    schedule = load_current_schedule()
    item = next((row for row in schedule.get('items', []) if row.get('domain') == domain), None)
    if not item: raise ValueError('Domain missing from current schedule')
    if item.get('status') == 'published' and item.get('publicUrl'):
        return {'status': 'already_published', 'state': 'published', 'publicPublicationVerified': True, 'httpStatus': 200, 'publicUrl': item['publicUrl'], 'title': item.get('title', domain), 'domain': domain}
    if (item.get('retryable') is False or item.get('status') in (
            'published', 'published_verified', 'verified', 'accepted', 'submitted',
            'submitting', 'submission_unknown', 'unknown', 'pending_effect', 'verification_pending')
            or any(item.get(key) for key in ('submissionStarted', 'submittedAt', 'submissionStartedAt', 'preCommitIntent'))):
        raise RuntimeError('Existing publication state requires reconciliation before another attempt')
    if item.get('artifactFolder'):
        prior_folder = (BASE_DIR / item['artifactFolder']).resolve()
        if (not prior_folder.is_relative_to((BASE_DIR / 'output').resolve())
                or (prior_folder / 'publication-receipt.json').exists()):
            raise RuntimeError('Authoritative artifact folder requires reconciliation before another attempt')
    folder = Path(artifact_folder).resolve() if artifact_folder else BASE_DIR / item.get('artifactFolder', '')
    if (folder / 'publication-receipt.json').exists():
        raise RuntimeError('Existing publication receipt requires reconciliation before another attempt')
    if not artifact_folder and not (folder / 'article.json').is_file():
        folder = BASE_DIR / 'output' / ('basic-' + domain + '-' + uuid.uuid4().hex[:10])
    if not folder.resolve().is_relative_to((BASE_DIR / 'output').resolve()):
        raise ValueError('Article folder must be inside channel output')
    folder.mkdir(parents=True, exist_ok=True)
    item.update(artifactFolder=str(folder.relative_to(BASE_DIR)), attemptStartedAt=stamp(),
                attemptCount=item.get('attemptCount', 0)+1, totalAttempts=item.get('totalAttempts', 0)+1)
    save_schedule_file(SCHEDULE_JSON, schedule)
    try:
        return _complete_basic_posting(domain, item, folder, schedule, prepare_only)
    except Exception as exc:
        try:
            record_basic_failure(domain, schedule['date'], item['attemptStartedAt'], folder, exc)
        except Exception as recording_error:
            exc.add_note('CF failure ledger update failed: ' + type(recording_error).__name__)
        raise


def _complete_basic_posting(domain, item, folder, schedule, prepare_only):
    from common.dashboard_jobs import write
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
