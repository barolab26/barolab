"""Shared CF table presentation for new posts and content-preserving repairs."""
from bs4 import BeautifulSoup

VERSION = 'cf-responsive-table-v1'
WRAPPER = 'overflow-x:auto;max-width:100%;min-width:0;margin:20px 0;-webkit-overflow-scrolling:touch'
TABLE = 'width:100%;border-collapse:collapse;font-size:15px;text-align:left;border-top:2px solid #2563eb'
HEADER = 'background:#f8fafc;padding:12px 14px;font-weight:700;border-bottom:1px solid #cbd5e1;text-align:left;overflow-wrap:anywhere;word-break:normal;white-space:normal'
CELL = 'padding:10px 14px;border-bottom:1px solid #f1f5f9;overflow-wrap:anywhere;word-break:normal;white-space:normal'
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


def style_tables(html):
    if '<table' not in html.lower():return html
    soup=BeautifulSoup(html,'html.parser')
    for table in list(soup.find_all('table')):
        parent=table.parent
        if parent.name=='div' and (parent.get('data-cf-table-style')==VERSION or
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


if __name__=='__main__':
    import argparse,json
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--repair-recent',action='store_true');parser.add_argument('--days',type=int,choices=range(1,31),default=7)
    args=parser.parse_args()
    if not args.repair_recent:parser.error('--repair-recent is required')
    folder,report=repair_recent(args.days)
    print(json.dumps({'report':str(folder),'updated':len(report['posts']),'errors':len(report['errors'])},ensure_ascii=False))
    if report['errors']:raise SystemExit(1)
