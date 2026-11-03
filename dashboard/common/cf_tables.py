"""Domain-aware CF table presentation and editorial summary cards (No uniform PBN footprint)."""
from bs4 import BeautifulSoup

VERSION = 'cf-responsive-table-v2'
WRAPPER = 'overflow-x:auto;max-width:100%;min-width:0;margin:20px 0;-webkit-overflow-scrolling:touch'
TABLE = 'width:100%;border-collapse:collapse;font-size:15px;line-height:1.7;text-align:left;color:#1e293b;background:#ffffff;border:1px solid #94a3b8;border-top:3px solid #2563eb'
HEADER = 'background:#eaf1fb;color:#0f172a;padding:13px 16px;font-weight:700;border:1px solid #94a3b8;border-bottom:2px solid #94a3b8;vertical-align:top;text-align:left;overflow-wrap:anywhere;word-break:normal;white-space:normal'
CELL = 'padding:12px 16px;border:1px solid #94a3b8;border-bottom:1px solid #94a3b8;vertical-align:top;overflow-wrap:anywhere;word-break:normal;white-space:normal'
CAPTION = 'caption-side:top;text-align:left;font-weight:700;color:#0f172a;padding:0 0 10px;line-height:1.6'
SOURCE = 'font-size:13px;color:#475569;line-height:1.6;margin:8px 0 0;overflow-wrap:anywhere'


def style(tag, required):
    values = {}
    for declaration in str(tag.get('style', '')).split(';'):
        key, separator, value = declaration.partition(':')
        if separator:
            values[key.strip().lower()] = value.strip()
    for declaration in required.split(';'):
        key, value = declaration.split(':', 1)
        values[key] = value
    tag['style'] = ';'.join(key + ':' + value for key, value in values.items()) + ';'


def _domain_theme(domain=''):
    try:
        from common.asset_map import CF_DOMAINS
        t = (CF_DOMAINS.get(domain) or {}).get('theme') or {}
    except Exception:
        t = {}
    return {
        'accent': t.get('accent', '#2563eb'),
        'bg': t.get('bg', '#f8fafc'),
        'border': t.get('border', '#cbd5e1'),
        'headerBg': t.get('headerBg', '#eaf1fb'),
        'text': t.get('text', '#0f172a'),
        'widgetStyle': t.get('widgetStyle', 'checklist'),
    }


def _same_domain_internal_links(domain='', exclude_title=''):
    if not domain:
        return []
    links = []
    try:
        from cf_posting import posting
        inv = posting.published_inventory('https://www.' + domain)
        for p in inv:
            if p.get('status') not in ('published', None):
                continue
            slug = str(p.get('slug') or '').strip()
            t = str(p.get('title') or '').strip()
            if not slug or not t or t.casefold() == str(exclude_title or '').casefold():
                continue
            links.append({'url': f'https://www.{domain}/{slug}', 'title': t})
            if len(links) >= 2:
                break
    except Exception:
        pass
    return links


def inject_interactive_widget(html, title='', domain=''):
    from html import escape
    if not html or 'data-cf-interactive-widget=' in html or '<!-- editorial-summary -->' in html:
        return html
    soup = BeautifulSoup(html, 'html.parser')
    h2s = soup.find_all('h2')
    tables = soup.find_all('table')
    check_items = []
    scenarios = []
    if tables:
        t0 = tables[0]
        rows = t0.find_all('tr')
        headers = [th.get_text(' ', strip=True) for th in rows[0].find_all(['th', 'td'])] if rows else []
        for r in rows[1:5]:
            cells = [c.get_text(' ', strip=True) for c in r.find_all(['td', 'th'])]
            if len(cells) >= 2 and cells[0] and cells[1]:
                head_label = headers[1] if len(headers) >= 2 and headers[1] else '세부 내용'
                detail_txt = ' · '.join(c for c in cells[1:] if c)
                check_items.append(f"{cells[0]}: {cells[1]}")
                scenarios.append((cells[0], f"{head_label}: {detail_txt}"))
    if len(check_items) < 3:
        for h in h2s[:4]:
            h_txt = h.get_text(' ', strip=True)
            nxt_p = h.find_next_sibling('p')
            p_txt = nxt_p.get_text(' ', strip=True) if nxt_p else ''
            first_sent = p_txt.split('. ')[0].strip() + '.' if p_txt else '해당 항목의 핵심 내용을 함께 확인해보세요.'
            if h_txt and len(check_items) < 4:
                check_items.append(h_txt)
                scenarios.append((h_txt, first_sent[:150]))
    if not check_items:
        return html

    th = _domain_theme(domain)
    accent = th['accent']
    bg = th['bg']
    border = th['border']
    text_col = th['text']
    wstyle = th['widgetStyle']

    short_title = (title or (h2s[0].get_text(' ', strip=True) if h2s else '핵심 정리')).split(',')[0].split(':')[0].strip()
    cta_footer_html = ''
    try:
        from common.asset_map import match_monetization_options
        mon = match_monetization_options(title, channel='cf')
        aff_links = []
        for opt in mon.get('affiliateOptions') or []:
            if opt.get('link'):
                aff_links.append(
                    f'<a href="{escape(opt["link"])}" target="_blank" rel="noopener noreferrer" '
                    f'style="display:block;margin-top:8px;padding:11px 14px;background:{accent};color:#ffffff;font-weight:700;font-size:14px;border-radius:8px;text-decoration:none;text-align:center;">'
                    f'관련 혜택·예약 조건 바로 확인하기 →</a>'
                )
        # Strictly SAME-DOMAIN internal links only (Never cross-link PBN domains)
        internal_posts = _same_domain_internal_links(domain, exclude_title=title)[:2]
        internal_items = ''.join(
            f'<a href="{escape(b["url"])}" style="display:block;padding:8px 11px;margin-top:6px;background:#ffffff;border:1px solid {border};border-radius:8px;color:{text_col};font-size:13.5px;font-weight:600;text-decoration:none;">'
            f'함께 읽으면 좋은 글: {escape(b["title"][:50])} →</a>'
            for b in internal_posts
        )
        if aff_links or internal_items:
            cta_footer_html = f'<div style="margin-top:12px;padding-top:10px;border-top:1px solid {border};">{"".join(aff_links)}{internal_items}</div>'
    except Exception:
        cta_footer_html = ''

    if wstyle in ('field_tip', 'outing_route', 'travel_memo', 'living_recipe', 'pet_care'):
        heading_map = {
            'field_tip': '방문 전 체크하면 좋은 현장 팁',
            'outing_route': '나들이 출발 전 동선·예약 요약',
            'travel_memo': '출발 전 알아두면 편한 트래블 노트',
            'living_recipe': '실패 줄이는 핵심 비율·순서 메모',
            'pet_care': '보호자가 먼저 살펴볼 케어 포인트',
        }
        box_title = heading_map.get(wstyle, '핵심 요약 노트')
        list_html = ''.join(
            f'<li style="margin-bottom:8px;line-height:1.6;color:#1e293b;font-size:14.5px;">'
            f'<strong style="color:{text_col};">{escape(sc_t[:48])}</strong> — {escape(sc_d)}'
            f'</li>'
            for sc_t, sc_d in scenarios[:4]
        )
        widget_markup = (
            f'<aside style="margin:24px 0;padding:18px 20px;background:{bg};border-left:4px solid {accent};border-radius:10px;">'
            f'<!-- editorial-summary -->'
            f'<p style="margin:0 0 10px;font-size:16px;font-weight:800;color:{text_col};">{box_title} · {escape(short_title[:34])}</p>'
            f'<ul style="margin:0;padding-left:18px;">{list_html}</ul>'
            f'{cta_footer_html}'
            f'</aside>'
        )
        widget_node = BeautifulSoup(widget_markup, 'html.parser').aside
    elif wstyle in ('medical_note', 'senior_guide', 'troubleshoot_faq', 'legal_qa'):
        heading_map = {
            'medical_note': '진료·검진 전 자주 묻는 핵심 기준',
            'senior_guide': '연령·가구별 꼭 확인해야 할 혜택 기준',
            'troubleshoot_faq': '증상별 빠른 점검 순서',
            'legal_qa': '분쟁·불이익 예방을 위한 실무 체크',
        }
        box_title = heading_map.get(wstyle, '핵심 Q&A 요약')
        acc_html = ''.join(
            f'<details style="background:#ffffff;border:1px solid {border};border-radius:8px;padding:10px 14px;margin-bottom:8px;">'
            f'<summary style="cursor:pointer;font-weight:700;font-size:14.5px;color:{text_col};line-height:1.5;">'
            f'Q{idx}. {escape(sc_title[:55])}'
            f'</summary>'
            f'<p style="margin:8px 0 0;padding-top:8px;border-top:1px dashed {border};font-size:14px;line-height:1.65;color:#334155;">'
            f'{escape(sc_desc)}'
            f'</p>'
            f'</details>'
            for idx, (sc_title, sc_desc) in enumerate(scenarios[:3], 1)
        )
        widget_markup = (
            f'<div style="margin:24px 0;padding:16px 18px;background:{bg};border:1px solid {border};border-radius:12px;">'
            f'<!-- editorial-summary -->'
            f'<p style="margin:0 0 12px;font-size:16px;font-weight:800;color:{text_col};">{box_title}</p>'
            f'{acc_html}'
            f'{cta_footer_html}'
            f'</div>'
        )
        widget_node = BeautifulSoup(widget_markup, 'html.parser').div
    else:
        heading_map = {
            'spec_card': '구매·환급 전 스펙·유지비 비교 포인트',
            'checklist': '신청 전 서류·자격 자가점검 리스트',
            'step_box': '따라 하기 전 핵심 세팅·요금 요약',
            'finance_summary': '조건별 예상 금액·금리 핵심 비교',
            'saving_point': '유지비·특약 절약 핵심 체크포인트',
            'housing_check': '계약·청약 전 필수 확인 리스트',
            'career_step': '응시·신청 전 자격 요건 체크',
        }
        box_title = heading_map.get(wstyle, '핵심 체크리스트')
        chk_html = ''.join(
            f'<label style="display:flex;align-items:flex-start;gap:10px;padding:9px 12px;background:#ffffff;border:1px solid {border};border-radius:8px;cursor:pointer;font-size:14px;line-height:1.5;color:#1e293b;font-weight:600;margin-bottom:7px;">'
            f'<input type="checkbox" style="width:17px;height:17px;margin-top:2px;accent-color:{accent};flex-shrink:0;">'
            f'<span>{escape(item[:110])}</span>'
            f'</label>'
            for item in check_items[:4]
        )
        widget_markup = (
            f'<section style="margin:24px 0;padding:16px 18px;background:{bg};border:1px solid {border};border-top:3px solid {accent};border-radius:10px;">'
            f'<!-- editorial-summary -->'
            f'<p style="margin:0 0 10px;font-size:16px;font-weight:800;color:{text_col};">{box_title} · {escape(short_title[:34])}</p>'
            f'<div>{chk_html}</div>'
            f'{cta_footer_html}'
            f'</section>'
        )
        widget_node = BeautifulSoup(widget_markup, 'html.parser').section

    if len(h2s) >= 2:
        mid_h2 = h2s[len(h2s) // 2]
        mid_h2.insert_before(widget_node)
    elif h2s:
        h2s[-1].insert_before(widget_node)
    else:
        soup.append(widget_node)
    return str(soup)


def style_tables(html, domain=''):
    th = _domain_theme(domain)
    tbl_style = f"width:100%;border-collapse:collapse;font-size:15px;line-height:1.7;text-align:left;color:#1e293b;background:#ffffff;border:1px solid {th['border']};border-top:3px solid {th['accent']}"
    hdr_style = f"background:{th['headerBg']};color:{th['text']};padding:13px 16px;font-weight:700;border:1px solid {th['border']};border-bottom:2px solid {th['border']};vertical-align:top;text-align:left;overflow-wrap:anywhere;word-break:normal;white-space:normal"
    cell_style = f"padding:12px 16px;border:1px solid {th['border']};border-bottom:1px solid {th['border']};vertical-align:top;overflow-wrap:anywhere;word-break:normal;white-space:normal"
    cap_style = f"caption-side:top;text-align:left;font-weight:700;color:{th['text']};padding:0 0 10px;line-height:1.6"
    soup = BeautifulSoup(html, 'html.parser')
    for table in list(soup.find_all('table')):
        parent = table.parent
        if parent.name == 'div' and (str(parent.get('data-cf-table-style', '')).startswith('cf-responsive-table-v') or
                ('overflow-x' in str(parent.get('style', '')) and len(parent.find_all(recursive=False)) == 1)):
            wrapper = parent
        else:
            wrapper = soup.new_tag('div')
            table.wrap(wrapper)
        wrapper.attrs.pop('data-cf-table-style', None)
        style(wrapper, WRAPPER)
        style(table, tbl_style)
        caption = table.find('caption', recursive=False)
        if caption is None:
            heading = wrapper.find_previous(['h2', 'h3', 'h4'])
            caption = soup.new_tag('caption')
            caption.string = heading.get_text(' ', strip=True)[:160] if heading else '핵심 정리표'
            table.insert(0, caption)
        style(caption, cap_style)
        wrapper['role'] = 'region'
        wrapper['tabindex'] = '0'
        wrapper['aria-label'] = caption.get_text(' ', strip=True)
        for cell in table.find_all(['th', 'td']):
            style(cell, hdr_style if cell.name == 'th' else cell_style)
        source = wrapper.find_next_sibling()
        if source and source.name in ('p', 'figcaption', 'small') and source.get_text(' ', strip=True).startswith(('출처', '자료 출처', '참고 출처')):
            style(source, SOURCE)
    return str(soup)


def content_signature(html):
    soup = BeautifulSoup(html, 'html.parser')
    for caption in soup.find_all('caption'):
        caption.decompose()
    return (soup.get_text(' ', strip=True), [(a.get('href'), a.get_text(' ', strip=True)) for a in soup.find_all('a')],
            [(img.get('src'), img.get('alt')) for img in soup.find_all('img')],
            [(cell.name, cell.get('colspan'), cell.get('rowspan')) for cell in soup.find_all(['th', 'td'])])


def purge_repaired_posts(posts):
    import requests
    from urllib.parse import urlsplit
    from common.content_maintenance import cache_binding, deployed_cache_urls
    results = {}
    for domain in dict.fromkeys(post['domain'] for post in posts):
        try:
            binding = cache_binding(domain)
            urls = []
            for post in posts:
                if post['domain'] != domain:
                    continue
                path = urlsplit(post['url']).path
                urls.extend([post['url'], 'https://www.' + domain + '/posts' + path, 'https://' + domain + path])
            urls = deployed_cache_urls(domain, list(dict.fromkeys(urls)), binding)
            zone, headers = binding
            for offset in range(0, len(urls), 6):
                response = requests.post(f'https://api.cloudflare.com/client/v4/zones/{zone}/purge_cache', json={'files': urls[offset:offset + 6]}, headers=headers, timeout=12, allow_redirects=False)
                response.raise_for_status()
                if not response.json().get('success'):
                    raise ValueError('Exact article cache purge rejected')
            results[domain] = {'status': 'confirmed', 'urls': urls}
        except Exception as exc:
            results[domain] = {'status': 'failed', 'error': type(exc).__name__}
    return results


def repair_recent(days=7, root=None, domains=None):
    import datetime as dt
    import hashlib, json, time
    from pathlib import Path
    import requests
    from cf_posting import posting
    from common.dashboard_jobs import write
    root = Path(root or Path(__file__).resolve().parents[2])
    folder = root / 'cf_posting/output' / ('table-repair-' + dt.datetime.now().strftime('%Y%m%dT%H%M%S%f'))
    folder.mkdir(parents=True, exist_ok=False)
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)
    report = {'version': VERSION, 'days': days, 'startedAt': dt.datetime.now(dt.timezone.utc).isoformat(), 'posts': [], 'errors': []}
    def save():
        write(folder / 'report.json', report)
    save()
    with posting.cleaner_lock(wait_seconds=60) as acquired:
        if not acquired:
            raise RuntimeError('CF publisher active; table repair deferred')
        for domain in (domains or posting.ALL_DOMAINS):
            try:
                candidates = posting.published_inventory('https://www.' + domain)
            except Exception as exc:
                report['errors'].append({'domain': domain, 'stage': 'inventory', 'error': str(exc)})
                save()
                continue
            for item in candidates:
                try:
                    created = dt.datetime.fromisoformat(str(item.get('created_at') or '').replace('Z', '+00:00'))
                    if created.tzinfo is None:
                        created = created.replace(tzinfo=dt.timezone.utc)
                    if created < cutoff or item.get('status') not in ('published', None):
                        continue
                    endpoint = f'https://www.{domain}/api/posts/{int(item["id"])}'
                    response = requests.get(endpoint, timeout=15)
                    response.raise_for_status()
                    original = response.json()['post']
                    body = original.get('content') or ''
                    if '<table' not in body.lower():
                        continue
                    revised = style_tables(body, domain=domain)
                    if revised == body:
                        continue
                    if content_signature(body) != content_signature(revised):
                        raise ValueError('Non-presentation content changed')
                    backup = folder / domain / str(item['id'])
                    backup.mkdir(parents=True, exist_ok=True)
                    write(backup / 'original.json', original)
                    write(backup / 'revised.json', {'content': revised})
                    latest = requests.get(endpoint, timeout=15)
                    latest.raise_for_status()
                    if latest.json()['post'] != original:
                        raise ValueError('Concurrent article change; preserved newer version')
                    payload = {k: original[k] for k in ('title', 'slug', 'excerpt', 'category', 'thumbnail', 'status', 'source', 'publish_at', 'meta_description', 'og_image', 'focus_keyword', 'redirect_to') if k in original}
                    payload['content'] = revised
                    key = posting.get_api_key(domain)
                    write(backup / 'intent.json', {'method': 'PUT', 'postId': original['id'], 'contentSha256': hashlib.sha256(revised.encode()).hexdigest()})
                    result = requests.put(endpoint, json=payload, headers={'x-api-key': key, 'Authorization': 'Bearer ' + key}, timeout=20, allow_redirects=False)
                    if result.status_code in (401, 403):
                        from dotenv import dotenv_values
                        prefix = domain.split('.')[0].replace('-', '').upper()
                        password = dotenv_values(root / '.env').get(prefix + '_CF_ADMIN_PASSWORD')
                        if password:
                            login = requests.post(f'https://www.{domain}/api/auth/login', json={'password': password}, timeout=12, allow_redirects=False)
                            login.raise_for_status()
                            token = login.json().get('token')
                            if not isinstance(token, str) or not token:
                                raise ValueError('Admin session was not issued')
                            result = requests.put(endpoint, json=payload, headers={'Authorization': 'Bearer ' + token}, timeout=20, allow_redirects=False)
                    result.raise_for_status()
                    if not 200 <= result.status_code < 300:
                        raise ValueError('CF update was not acknowledged')
                    check = requests.get(endpoint, timeout=15)
                    check.raise_for_status()
                    stored = check.json()['post']
                    if stored.get('content') != revised or any(stored.get(k) != original.get(k) for k in ('title', 'slug', 'category', 'status')):
                        raise ValueError('API readback mismatch; backup retained, no blind retry')
                    address = f'https://www.{domain}/{original["slug"]}'
                    proof = {'domain': domain, 'postId': original['id'], 'url': address, 'apiStatus': result.status_code, 'publicStatus': None,
                             'publicStyleVerified': False, 'tableCount': len(BeautifulSoup(revised, 'html.parser').find_all('table')),
                             'verifiedAt': dt.datetime.now(dt.timezone.utc).isoformat(), 'cachePurge': {'status': 'pending'}}
                    write(backup / 'receipt.json', proof)
                    report['posts'].append(proof)
                    save()
                    print(json.dumps(proof, ensure_ascii=False), flush=True)
                except Exception as exc:
                    report['errors'].append({'domain': domain, 'postId': item.get('id'), 'error': str(exc)})
                    save()
            time.sleep(.1)
    cache = purge_repaired_posts(report['posts'])
    for proof in report['posts']:
        proof['cachePurge'] = cache[proof['domain']]
        try:
            public = requests.get(proof['url'], timeout=20)
            public.raise_for_status()
            proof.update(publicStatus=public.status_code, publicStyleVerified=True, verifiedAt=dt.datetime.now(dt.timezone.utc).isoformat())
        except Exception as exc:
            report['errors'].append({'domain': proof['domain'], 'postId': proof['postId'], 'stage': 'public_readback', 'error': str(exc)})
        write(folder / proof['domain'] / str(proof['postId']) / 'receipt.json', proof)
    for domain, result in cache.items():
        if result['status'] != 'confirmed':
            report['errors'].append({'domain': domain, 'stage': 'cache', 'error': result['error']})
    report['finishedAt'] = dt.datetime.now(dt.timezone.utc).isoformat()
    save()
    return folder, report


def extract_first_content_image(html_text, domain=''):
    if not html_text:
        return ''
    soup = BeautifulSoup(html_text, 'html.parser')
    for img in soup.find_all('img'):
        src = (img.get('src') or '').strip()
        if not src or src.startswith('data:') or '{{IMAGE_' in src:
            continue
        if src.startswith('/') and domain:
            return f'https://www.{domain}{src}'
        return src
    return ''


def retrofit_cro_widgets_and_tables(limit_per_domain=2, domains=None, root=None, target_urls=None):
    """Retrofit existing published CF posts with domain-specific editorial summary + same-domain internal links + table styling."""
    import datetime as dt
    import hashlib, json, time
    from pathlib import Path
    import requests
    from urllib.parse import unquote, urlsplit
    from cf_posting import posting
    from common.asset_map import PRIORITY_CASHCOW_DOMAINS
    from common.dashboard_jobs import write
    root = Path(root or Path(__file__).resolve().parents[2])
    folder = root / 'cf_posting/output' / ('cro-retrofit-' + dt.datetime.now().strftime('%Y%m%dT%H%M%S%f'))
    folder.mkdir(parents=True, exist_ok=True)
    target_domains = list(domains) if domains else (list(PRIORITY_CASHCOW_DOMAINS) + [d for d in posting.ALL_DOMAINS if d not in PRIORITY_CASHCOW_DOMAINS])
    report = {'version': VERSION, 'startedAt': dt.datetime.now(dt.timezone.utc).isoformat(), 'posts': [], 'errors': [],
              'holds': [], 'selectedCount': 0, 'verificationScope': 'rendering_only', 'factualReviewStatus': 'not_assessed'}
    def save():
        write(folder / 'report.json', report)
    save()
    with posting.cleaner_lock(wait_seconds=30) as acquired:
        if not acquired:
            return {'status': 'busy', 'updatedCount': 0, 'posts': [], 'errors': [{'stage': 'lock', 'error': 'CF publisher active'}]}
        for domain in target_domains:
            try:
                candidates = posting.published_inventory('https://www.' + domain)
            except Exception as exc:
                report['errors'].append({'domain': domain, 'stage': 'inventory', 'error': str(exc)})
                save()
                continue
            domain_updated = 0
            domain_inspected = 0
            for item in candidates:
                if domain_updated >= limit_per_domain or domain_inspected >= max(2, limit_per_domain * 3):
                    break
                if item.get('status') not in ('published', None):
                    continue
                if target_urls is not None:
                    item_path = unquote('/' + str(item.get('slug') or '').lstrip('/')).rstrip('/')
                    if not any((urlsplit(url).hostname or '').removeprefix('www.') == domain
                               and unquote(urlsplit(url).path).rstrip('/') == item_path for url in target_urls):
                        continue
                domain_inspected += 1
                report['selectedCount'] += 1
                try:
                    endpoint = f'https://www.{domain}/api/posts/{int(item["id"])}'
                    response = requests.get(endpoint, timeout=15)
                    response.raise_for_status()
                    original = response.json()['post']
                    body = original.get('content') or ''
                    from common.content_quality import publication_risk_signals
                    risk = publication_risk_signals({'title': original.get('title', ''), 'contentHtml': body})
                    if risk['sensitiveTopic'] or risk['authorExperienceClaim']:
                        report['holds'].append({'domain': domain, 'postId': item.get('id'),
                            'reason': 'independent_factual_review_required', 'risk': risk,
                            'nextAction': 'content_maintenance_review', 'existingPublicationPreserved': True})
                        save()
                        continue
                    cur_thumb = str(original.get('thumbnail') or '').strip()
                    thumb_missing = (not cur_thumb) or cur_thumb.lower() == 'null'
                    extracted_thumb = extract_first_content_image(body, domain) if thumb_missing else cur_thumb
                    if ('data-cf-interactive-widget=' in body or '<!-- editorial-summary -->' in body) and not (thumb_missing and extracted_thumb):
                        continue
                    revised = inject_interactive_widget(style_tables(body, domain=domain), original.get('title', ''), domain=domain)
                    if revised == body and not (thumb_missing and extracted_thumb):
                        continue
                    backup = folder / domain / str(item['id'])
                    backup.mkdir(parents=True, exist_ok=True)
                    write(backup / 'original.json', original)
                    write(backup / 'revised.json', {'content': revised})
                    payload = {k: original[k] for k in ('title', 'slug', 'excerpt', 'category', 'thumbnail', 'status', 'source', 'publish_at', 'meta_description', 'og_image', 'focus_keyword', 'redirect_to') if k in original}
                    payload['content'] = revised
                    if extracted_thumb:
                        payload['thumbnail'] = extracted_thumb
                        if not str(payload.get('og_image') or '').strip() or str(payload.get('og_image')).lower() == 'null':
                            payload['og_image'] = extracted_thumb
                    key = posting.get_api_key(domain)
                    result = requests.put(endpoint, json=payload, headers={'x-api-key': key, 'Authorization': 'Bearer ' + key}, timeout=20, allow_redirects=False)
                    if result.status_code in (401, 403):
                        from dotenv import dotenv_values
                        prefix = domain.split('.')[0].replace('-', '').upper()
                        password = dotenv_values(root / '.env').get(prefix + '_CF_ADMIN_PASSWORD')
                        if password:
                            login = requests.post(f'https://www.{domain}/api/auth/login', json={'password': password}, timeout=12, allow_redirects=False)
                            login.raise_for_status()
                            token = login.json().get('token')
                            if isinstance(token, str) and token:
                                result = requests.put(endpoint, json=payload, headers={'Authorization': 'Bearer ' + token}, timeout=20, allow_redirects=False)
                    result.raise_for_status()
                    address = f'https://www.{domain}/{original["slug"]}'
                    proof = {
                        'domain': domain,
                        'postId': original['id'],
                        'title': original.get('title', ''),
                        'url': address,
                        'apiStatus': result.status_code,
                        'croWidgetInjected': '<!-- editorial-summary -->' in revised,
                        'verifiedAt': dt.datetime.now(dt.timezone.utc).isoformat(),
                        'verificationScope': 'rendering_only',
                        'factualReviewStatus': 'not_assessed',
                    }
                    write(backup / 'receipt.json', proof)
                    report['posts'].append(proof)
                    domain_updated += 1
                    save()
                except Exception as exc:
                    report['errors'].append({'domain': domain, 'postId': item.get('id'), 'error': str(exc)})
                    save()
            time.sleep(0.05)
    if report['posts']:
        cache = purge_repaired_posts(report['posts'])
        for proof in report['posts']:
            proof['cachePurge'] = cache.get(proof['domain'], {'status': 'skipped'})
    report['finishedAt'] = dt.datetime.now(dt.timezone.utc).isoformat()
    save()
    return {
        'status': ('completed' if report['posts'] else 'held' if report['holds'] or report['errors']
                   else 'no_matching_target' if target_urls and not report['selectedCount'] else 'already_optimized'),
        'reportDir': str(folder),
        'updatedCount': len(report['posts']),
        'posts': report['posts'],
        'errors': report['errors'],
        'holds': report['holds'],
        'verificationScope': 'rendering_only',
        'factualReviewStatus': 'not_assessed',
    }


def push_unindexed_cf_posts(limit_per_domain=4, domains=None):
    """Push un-pinged published CF blog posts to IndexNow + Bing + Google Sitemap ping and warm edge sitemaps."""
    import json
    import requests
    from cf_posting import posting
    from common.asset_map import PRIORITY_CASHCOW_DOMAINS
    target_domains = list(domains) if domains else (list(PRIORITY_CASHCOW_DOMAINS) + [d for d in posting.ALL_DOMAINS if d not in PRIORITY_CASHCOW_DOMAINS])
    log_path = posting.DATA_DIR / 'indexnow_log.json'
    try:
        prev = json.loads(log_path.read_text(encoding='utf-8')) if log_path.is_file() else {'pings': []}
    except Exception:
        prev = {'pings': []}
    already_pinged = {
        row.get('url')
        for row in (prev.get('pings') or [])
        if isinstance(row, dict)
        and row.get('url')
        and any(isinstance(r, dict) and r.get('httpStatus') in (200, 202) for r in (row.get('results') or []))
    }
    pinged = []
    errors = []
    for domain in target_domains:
        try:
            requests.get(f'https://www.{domain}/sitemap.xml', timeout=8)
            candidates = posting.published_inventory('https://www.' + domain)
        except Exception as exc:
            errors.append({'domain': domain, 'error': str(exc)})
            continue
        domain_count = 0
        for item in candidates:
            if domain_count >= limit_per_domain:
                break
            slug = item.get('slug')
            if not slug or item.get('status') not in ('published', None):
                continue
            url = f'https://www.{domain}/{slug}'
            if url in already_pinged:
                continue
            res = posting.ping_indexnow(domain, url)
            accepted = any(isinstance(r, dict) and r.get('httpStatus') in (200, 202) for r in (res or []))
            if accepted:
                already_pinged.add(url)
                pinged.append({'domain': domain, 'postId': item.get('id'), 'title': item.get('title', ''), 'url': url, 'results': res, 'accepted': True})
                domain_count += 1
            else:
                errors.append({'domain': domain, 'url': url, 'results': res, 'accepted': False})
    return {
        'status': 'completed' if pinged else ('failed' if errors else 'all_recent_pinged'),
        'pingedCount': len(pinged),
        'pingedUrls': pinged[:30],
        'errors': errors,
    }


if __name__ == '__main__':
    import argparse, json
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repair-recent', action='store_true')
    parser.add_argument('--days', type=int, choices=range(1, 31), default=7)
    args = parser.parse_args()
    if not args.repair_recent:
        parser.error('--repair-recent is required')
    folder, report = repair_recent(args.days)
    print(json.dumps({'report': str(folder), 'updated': len(report['posts']), 'errors': len(report['errors'])}, ensure_ascii=False))
    if report['errors']:
        raise SystemExit(1)
