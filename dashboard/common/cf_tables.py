"""Shared CF table presentation for new posts and content-preserving repairs."""
from bs4 import BeautifulSoup

VERSION = 'cf-responsive-table-v2'
WRAPPER = 'overflow-x:auto;max-width:100%;min-width:0;margin:20px 0;-webkit-overflow-scrolling:touch'
TABLE = 'width:100%;border-collapse:collapse;font-size:15px;line-height:1.7;text-align:left;color:#1e293b;background:#ffffff;border:1px solid #94a3b8;border-top:3px solid #2563eb'
HEADER = 'background:#eaf1fb;color:#0f172a;padding:13px 16px;font-weight:700;border:1px solid #94a3b8;border-bottom:2px solid #94a3b8;vertical-align:top;text-align:left;overflow-wrap:anywhere;word-break:normal;white-space:normal'
CELL = 'padding:12px 16px;border:1px solid #94a3b8;border-bottom:1px solid #94a3b8;vertical-align:top;overflow-wrap:anywhere;word-break:normal;white-space:normal'
CAPTION = 'caption-side:top;text-align:left;font-weight:700;color:#0f172a;padding:0 0 10px;line-height:1.6'
SOURCE = 'font-size:13px;color:#475569;line-height:1.6;margin:8px 0 0;overflow-wrap:anywhere'


def style(tag, required):
    values={}
    for declaration in str(tag.get('style','')).split(';'):
        key,separator,value=declaration.partition(':')
        if separator:values[key.strip().lower()]=value.strip()
    for declaration in required.split(';'):
        key,value=declaration.split(':',1);values[key]=value
    tag['style']=';'.join(key+':'+value for key,value in values.items())+';'


def inject_interactive_widget(html, title=''):
    from html import escape
    if not html or 'data-cf-interactive-widget=' in html:
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
                head_label = headers[1] if len(headers) >= 2 and headers[1] else '핵심 기준'
                detail_txt = ' · '.join(c for c in cells[1:] if c)
                check_items.append(f"{cells[0]}: {cells[1]}")
                scenarios.append((cells[0], f"{head_label}: {detail_txt}"))
    if len(check_items) < 3:
        for h in h2s[:4]:
            h_txt = h.get_text(' ', strip=True)
            nxt_p = h.find_next_sibling('p')
            p_txt = nxt_p.get_text(' ', strip=True) if nxt_p else ''
            first_sent = p_txt.split('. ')[0].strip() + '.' if p_txt else '해당 구간의 세부 요건을 먼저 대조해보세요.'
            if h_txt and len(check_items) < 4:
                check_items.append(h_txt)
                scenarios.append((h_txt, first_sent[:150]))
    if not check_items:
        return html

    chk_html = ''.join(
        f'<label style="display:flex;align-items:flex-start;gap:10px;padding:10px 12px;background:#ffffff;border:1px solid #cbd5e1;border-radius:10px;cursor:pointer;font-size:14.5px;line-height:1.5;color:#0f172a;font-weight:600;margin-bottom:8px;">'
        f'<input type="checkbox" style="width:18px;height:18px;margin-top:2px;accent-color:#2563eb;flex-shrink:0;">'
        f'<span>{escape(item[:110])}</span>'
        f'</label>'
        for item in check_items[:4]
    )
    acc_html = ''.join(
        f'<details style="background:#ffffff;border:1px solid #bfdbfe;border-radius:10px;padding:10px 14px;margin-bottom:8px;">'
        f'<summary style="cursor:pointer;font-weight:800;font-size:14.5px;color:#1d4ed8;line-height:1.5;list-style:none;display:flex;justify-content:space-between;align-items:center;">'
        f'<span>👉 [내 상황 판독 {idx}] {escape(sc_title[:55])}</span>'
        f'<span style="font-size:12px;color:#2563eb;background:#eff6ff;padding:2px 8px;border-radius:999px;flex-shrink:0;">결과 보기 ▼</span>'
        f'</summary>'
        f'<div style="margin-top:10px;padding-top:10px;border-top:1px dashed #cbd5e1;font-size:14px;line-height:1.65;color:#1e293b;">'
        f'<strong style="color:#047857;">✔ 핵심 판독 기준:</strong> {escape(sc_desc)}'
        f'</div>'
        f'</details>'
        for idx, (sc_title, sc_desc) in enumerate(scenarios[:3], 1)
    )
    short_title = (title or (h2s[0].get_text(' ', strip=True) if h2s else '핵심 조건')).split(',')[0].strip()
    cta_footer_html = ''
    try:
        from common.asset_map import match_monetization_options, get_today_cf_bridge_targets
        mon = match_monetization_options(title, channel='cf')
        aff_links = []
        for opt in mon.get('affiliateOptions') or []:
            if opt.get('link'):
                aff_links.append(
                    f'<a href="{escape(opt["link"])}" target="_blank" rel="noopener noreferrer" '
                    f'style="display:block;margin-top:8px;padding:11px 14px;background:#1d4ed8;color:#ffffff;font-weight:700;font-size:14px;border-radius:10px;text-decoration:none;text-align:center;">'
                    f'✈️ 관련 특가 혜택·할인 조건 바로 확인하기 →</a>'
                )
        bridges = [b for b in (get_today_cf_bridge_targets(title) or []) if b.get('url') and b.get('title') and b.get('title') != title][:2]
        bridge_items = ''.join(
            f'<a href="{escape(b["url"])}" style="display:block;padding:8px 11px;margin-top:6px;background:#ffffff;border:1px solid #bfdbfe;border-radius:8px;color:#1e40af;font-size:13.5px;font-weight:600;text-decoration:none;">'
            f'📌 함께 확인하면 돈 아끼는 글: {escape(b["title"][:48])} →</a>'
            for b in bridges
        )
        if aff_links or bridge_items:
            cta_footer_html = f'<div style="margin-top:12px;padding-top:10px;border-top:1px solid #bfdbfe;">{"".join(aff_links)}{bridge_items}</div>'
    except Exception:
        cta_footer_html = ''
    widget_markup = (
        f'<section data-cf-interactive-widget="cf-diagnosis-v1" role="region" aria-label="3초 자가진단 판독기" '
        f'style="margin:26px 0;padding:18px 18px 14px;background:linear-gradient(180deg,#f8fafc 0%,#eff6ff 100%);border:2px solid #3b82f6;border-radius:14px;box-shadow:0 4px 14px rgba(37,99,235,0.08);">'
        f'<div style="display:flex;align-items:center;justify-content:space-between;gap:8px;margin-bottom:10px;flex-wrap:wrap;">'
        f'<strong style="font-size:16.5px;color:#0f172a;letter-spacing:-0.3px;">⚡ 3초 자가진단 체크리스트 · {escape(short_title[:36])}</strong>'
        f'<span style="font-size:12px;font-weight:800;color:#ffffff;background:#2563eb;padding:3px 9px;border-radius:999px;">터치하여 직접 체크</span>'
        f'</div>'
        f'<p style="margin:0 0 12px;font-size:13.5px;color:#475569;line-height:1.5;">스마트폰 화면에서 본인에게 해당하는 항목을 직접 눌러 체크하고, 아래 상황별 판독 결과를 펼쳐 확인해보세요.</p>'
        f'<div style="margin-bottom:12px;">{chk_html}</div>'
        f'<div>{acc_html}</div>'
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


def style_tables(html):
    soup=BeautifulSoup(html,'html.parser')
    for table in list(soup.find_all('table')):
        parent=table.parent
        if parent.name=='div' and (str(parent.get('data-cf-table-style','')).startswith('cf-responsive-table-v') or
                ('overflow-x' in str(parent.get('style','')) and len(parent.find_all(recursive=False))==1)):
            wrapper=parent
        else:
            wrapper=soup.new_tag('div');table.wrap(wrapper)
        wrapper['data-cf-table-style']=VERSION;style(wrapper,WRAPPER);style(table,TABLE)
        caption=table.find('caption',recursive=False)
        if caption is None:
            heading=wrapper.find_previous(['h2','h3','h4'])
            caption=soup.new_tag('caption');caption.string=heading.get_text(' ',strip=True)[:160] if heading else '정보 요약표'
            table.insert(0,caption)
        style(caption,CAPTION)
        wrapper['role']='region';wrapper['tabindex']='0';wrapper['aria-label']=caption.get_text(' ',strip=True)
        for cell in table.find_all(['th','td']):
            style(cell,HEADER if cell.name=='th' else CELL)
        # Preserve actual citations; presentation must never invent a source.
        source=wrapper.find_next_sibling()
        if source and source.name in ('p','figcaption','small') and source.get_text(' ',strip=True).startswith(('출처','자료 출처','참고 출처')):
            style(source,SOURCE)
    return str(soup)


def content_signature(html):
    soup=BeautifulSoup(html,'html.parser')
    for caption in soup.find_all('caption'):caption.decompose()
    return (soup.get_text(' ',strip=True),[(a.get('href'),a.get_text(' ',strip=True)) for a in soup.find_all('a')],
            [(img.get('src'),img.get('alt')) for img in soup.find_all('img')],
            [(cell.name,cell.get('colspan'),cell.get('rowspan')) for cell in soup.find_all(['th','td'])])


def purge_repaired_posts(posts):
    import requests
    from urllib.parse import urlsplit
    from common.content_maintenance import cache_binding,deployed_cache_urls
    results={}
    for domain in dict.fromkeys(post['domain'] for post in posts):
        try:
            binding=cache_binding(domain);urls=[]
            for post in posts:
                if post['domain']!=domain:continue
                path=urlsplit(post['url']).path
                urls.extend([post['url'],'https://www.'+domain+'/posts'+path,'https://'+domain+path])
            urls=deployed_cache_urls(domain,list(dict.fromkeys(urls)),binding)
            zone,headers=binding
            for offset in range(0,len(urls),6):
                response=requests.post(f'https://api.cloudflare.com/client/v4/zones/{zone}/purge_cache',json={'files':urls[offset:offset+6]},headers=headers,timeout=12,allow_redirects=False)
                response.raise_for_status()
                if not response.json().get('success'):raise ValueError('Exact article cache purge rejected')
            results[domain]={'status':'confirmed','urls':urls}
        except Exception as exc:results[domain]={'status':'failed','error':type(exc).__name__}
    return results


def repair_recent(days=7, root=None, domains=None):
    import datetime as dt
    import hashlib,json,time
    from pathlib import Path
    import requests
    from cf_posting import posting
    from common.dashboard_jobs import write
    root=Path(root or Path(__file__).resolve().parents[2])
    folder=root/'cf_posting/output'/('table-repair-'+dt.datetime.now().strftime('%Y%m%dT%H%M%S%f'))
    folder.mkdir(parents=True,exist_ok=False)
    cutoff=dt.datetime.now(dt.timezone.utc)-dt.timedelta(days=days)
    report={'version':VERSION,'days':days,'startedAt':dt.datetime.now(dt.timezone.utc).isoformat(),'posts':[],'errors':[]}
    def save():write(folder/'report.json',report)
    save()
    with posting.cleaner_lock(wait_seconds=60) as acquired:
        if not acquired:raise RuntimeError('CF publisher active; table repair deferred')
        for domain in (domains or posting.ALL_DOMAINS):
            try:
                candidates=posting.published_inventory('https://www.'+domain)
            except Exception as exc:
                report['errors'].append({'domain':domain,'stage':'inventory','error':str(exc)});save();continue
            for item in candidates:
                try:
                    created=dt.datetime.fromisoformat(str(item.get('created_at') or '').replace('Z','+00:00'))
                    if created.tzinfo is None:created=created.replace(tzinfo=dt.timezone.utc)
                    if created<cutoff or item.get('status') not in ('published',None):continue
                    endpoint=f'https://www.{domain}/api/posts/{int(item["id"])}'
                    response=requests.get(endpoint,timeout=15);response.raise_for_status();original=response.json()['post']
                    body=original.get('content') or ''
                    if '<table' not in body.lower():continue
                    revised=style_tables(body)
                    if revised==body:continue
                    if content_signature(body)!=content_signature(revised):raise ValueError('Non-presentation content changed')
                    backup=folder/domain/str(item['id']);backup.mkdir(parents=True,exist_ok=True)
                    write(backup/'original.json',original);write(backup/'revised.json',{'content':revised})
                    latest=requests.get(endpoint,timeout=15);latest.raise_for_status()
                    if latest.json()['post']!=original:raise ValueError('Concurrent article change; preserved newer version')
                    payload={k:original[k] for k in ('title','slug','excerpt','category','thumbnail','status','source','publish_at','meta_description','og_image','focus_keyword','redirect_to') if k in original}
                    payload['content']=revised
                    key=posting.get_api_key(domain)
                    write(backup/'intent.json',{'method':'PUT','postId':original['id'],'contentSha256':hashlib.sha256(revised.encode()).hexdigest()})
                    result=requests.put(endpoint,json=payload,headers={'x-api-key':key,'Authorization':'Bearer '+key},timeout=20,allow_redirects=False)
                    if result.status_code in (401,403):
                        from dotenv import dotenv_values
                        prefix=domain.split('.')[0].replace('-','').upper()
                        password=dotenv_values(root/'.env').get(prefix+'_CF_ADMIN_PASSWORD')
                        if password:
                            login=requests.post(f'https://www.{domain}/api/auth/login',json={'password':password},timeout=12,allow_redirects=False)
                            login.raise_for_status()
                            token=login.json().get('token')
                            if not isinstance(token,str) or not token:raise ValueError('Admin session was not issued')
                            result=requests.put(endpoint,json=payload,headers={'Authorization':'Bearer '+token},timeout=20,allow_redirects=False)
                    result.raise_for_status()
                    if not 200<=result.status_code<300:raise ValueError('CF update was not acknowledged')
                    check=requests.get(endpoint,timeout=15);check.raise_for_status();stored=check.json()['post']
                    if stored.get('content')!=revised or any(stored.get(k)!=original.get(k) for k in ('title','slug','category','status')):
                        raise ValueError('API readback mismatch; backup retained, no blind retry')
                    address=f'https://www.{domain}/{original["slug"]}'
                    proof={'domain':domain,'postId':original['id'],'url':address,'apiStatus':result.status_code,'publicStatus':None,
                           'publicStyleVerified':False,'tableCount':len(BeautifulSoup(revised,'html.parser').find_all('table')),
                           'verifiedAt':dt.datetime.now(dt.timezone.utc).isoformat(),'cachePurge':{'status':'pending'}}
                    write(backup/'receipt.json',proof);report['posts'].append(proof);save()
                    print(json.dumps(proof,ensure_ascii=False),flush=True)
                except Exception as exc:
                    report['errors'].append({'domain':domain,'postId':item.get('id'),'error':str(exc)});save()
            time.sleep(.1)
    cache=purge_repaired_posts(report['posts'])
    for proof in report['posts']:
        proof['cachePurge']=cache[proof['domain']]
        try:
            public=requests.get(proof['url'],timeout=20);public.raise_for_status()
            proof.update(publicStatus=public.status_code,publicStyleVerified=VERSION in public.text,verifiedAt=dt.datetime.now(dt.timezone.utc).isoformat())
            if not proof['publicStyleVerified']:raise ValueError('Public table style readback pending')
        except Exception as exc:report['errors'].append({'domain':proof['domain'],'postId':proof['postId'],'stage':'public_readback','error':str(exc)})
        write(folder/proof['domain']/str(proof['postId'])/'receipt.json',proof)
    for domain,result in cache.items():
        if result['status']!='confirmed':report['errors'].append({'domain':domain,'stage':'cache','error':result['error']})
    report['finishedAt']=dt.datetime.now(dt.timezone.utc).isoformat();save()
    return folder,report


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


def retrofit_cro_widgets_and_tables(limit_per_domain=2, domains=None, root=None):
    """Retrofit existing published CF posts with the 3-second CRO self-check + affiliate/internal bridge widget + table styling."""
    import datetime as dt
    import hashlib, json, time
    from pathlib import Path
    import requests
    from cf_posting import posting
    from common.asset_map import PRIORITY_CASHCOW_DOMAINS
    from common.dashboard_jobs import write
    root = Path(root or Path(__file__).resolve().parents[2])
    folder = root / 'cf_posting/output' / ('cro-retrofit-' + dt.datetime.now().strftime('%Y%m%dT%H%M%S%f'))
    folder.mkdir(parents=True, exist_ok=True)
    target_domains = list(domains) if domains else (list(PRIORITY_CASHCOW_DOMAINS) + [d for d in posting.ALL_DOMAINS if d not in PRIORITY_CASHCOW_DOMAINS])
    report = {'version': VERSION, 'startedAt': dt.datetime.now(dt.timezone.utc).isoformat(), 'posts': [], 'errors': []}
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
            for item in candidates:
                if domain_updated >= limit_per_domain:
                    break
                if item.get('status') not in ('published', None):
                    continue
                try:
                    endpoint = f'https://www.{domain}/api/posts/{int(item["id"])}'
                    response = requests.get(endpoint, timeout=15)
                    response.raise_for_status()
                    original = response.json()['post']
                    body = original.get('content') or ''
                    cur_thumb = str(original.get('thumbnail') or '').strip()
                    thumb_missing = (not cur_thumb) or cur_thumb.lower() == 'null'
                    extracted_thumb = extract_first_content_image(body, domain) if thumb_missing else cur_thumb
                    if 'data-cf-interactive-widget=' in body and ('<table' not in body.lower() or VERSION in body) and not (thumb_missing and extracted_thumb):
                        continue
                    revised = inject_interactive_widget(style_tables(body), original.get('title', ''))
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
                        'croWidgetInjected': 'data-cf-interactive-widget=' in revised,
                        'verifiedAt': dt.datetime.now(dt.timezone.utc).isoformat(),
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
        'status': 'completed' if report['posts'] else 'already_optimized',
        'reportDir': str(folder),
        'updatedCount': len(report['posts']),
        'posts': report['posts'],
        'errors': report['errors'],
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


if __name__=='__main__':
    import argparse,json
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--repair-recent',action='store_true');parser.add_argument('--days',type=int,choices=range(1,31),default=7)
    args=parser.parse_args()
    if not args.repair_recent:parser.error('--repair-recent is required')
    folder,report=repair_recent(args.days)
    print(json.dumps({'report':str(folder),'updated':len(report['posts']),'errors':len(report['errors'])},ensure_ascii=False))
    if report['errors']:raise SystemExit(1)
