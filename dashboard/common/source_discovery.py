"""Bounded search discovery; snippets never become article evidence."""
import os
from urllib.parse import urlsplit
import requests
from bs4 import BeautifulSoup


def search_urls(query):
    from dotenv import load_dotenv
    from pathlib import Path
    load_dotenv(Path(__file__).resolve().parents[2]/'.env')
    rows=[];seen=set()
    def add(url,title,provider):
        try:url=public_https_url(url)
        except (ValueError,RuntimeError):return
        if url in seen:return
        seen.add(url);rows.append(dict(url=url,title=BeautifulSoup(str(title),'html.parser').get_text(' ',strip=True),searchProvider=provider,position=len(rows)+1))
    client=os.getenv('NAVER_CLIENT_ID');secret=os.getenv('NAVER_CLIENT_SECRET')
    if client and secret:
        for kind in ('webkr','news','encyc'):
            try:
                response=requests.get('https://openapi.naver.com/v1/search/'+kind+'.json',
                    params={'query':query,'display':10},headers={'X-Naver-Client-Id':client,'X-Naver-Client-Secret':secret},timeout=8,allow_redirects=False)
                if response.status_code!=200:continue
                for item in response.json().get('items',[])[:10]:add(item.get('originallink') or item.get('link'),item.get('title'), 'naver-'+kind)
            except (requests.RequestException,ValueError,TypeError):continue
    if len(rows)<2:
        try:
            response=requests.get('https://www.bing.com/search',params={'q':query},timeout=8,allow_redirects=False)
            if response.status_code==200:
                soup=BeautifulSoup(response.text,'html.parser')
                for link in soup.select('li.b_algo h2 a[href]')[:10]:add(link['href'],link.get_text(),'bing-http')
        except (requests.RequestException,ValueError):pass
    return rows[:24]


# Public-source checks are transport validation, never editorial approval.
import ipaddress
import socket
from urllib.parse import urljoin, urlunsplit


def public_https_url(value):
    if not isinstance(value, str) or value != value.strip():
        raise ValueError('Invalid public source URL')
    p = urlsplit(value)
    host = (p.hostname or '').lower()
    if (p.scheme != 'https' or not host or p.username or p.password or p.port not in (None,443)
            or host == 'localhost' or host.endswith(('.local','.localhost','.internal','.test','.invalid'))
            or '.' not in host or '\\' in value):
        raise ValueError('Public HTTPS source required')
    try: address = ipaddress.ip_address(host)
    except ValueError: pass
    else:
        if not address.is_global: raise ValueError('Private source address rejected')
    return urlunsplit((p.scheme,p.netloc,p.path or '/',p.query,''))


def public_text(url, timeout=8):
    for _ in range(4):
        url = public_https_url(url)
        addresses = socket.getaddrinfo(urlsplit(url).hostname,443,type=socket.SOCK_STREAM)
        if not addresses or any(not ipaddress.ip_address(row[4][0]).is_global for row in addresses):
            raise ValueError('Source DNS is not exclusively public')
        with requests.get(url,timeout=timeout,allow_redirects=False,stream=True) as response:
            if response.status_code in (301,302,303,307,308):
                url = urljoin(url,response.headers['Location']); continue
            response.raise_for_status()
            content_type=response.headers.get('Content-Type','').lower()
            if 'html' not in content_type and not content_type.startswith('text/'):
                raise ValueError('Source is not a text document')
            chunks=[];size=0
            for chunk in response.iter_content(65536):
                size+=len(chunk)
                if size>2000000: raise ValueError('Source text exceeds the collection limit')
                chunks.append(chunk)
            soup=BeautifulSoup(b''.join(chunks),'html.parser')
            for tag in soup(['script','style','noscript','nav','footer']):tag.decompose()
            body=(soup.find('article') or soup.find('main') or soup).get_text(' ',strip=True)
            return {'url':url,'text':body[:9000]}
    raise ValueError('Too many source redirects')


def research(keyword, folder):
    from common.dashboard_jobs import write
    from datetime import datetime, timezone
    from common.crew_chat_bridge import emit_work_event, work_task_id
    task=work_task_id(folder)
    emit_work_event(actor='radar',actor_label='레이더',task_id=task,phase='progress',stage='researcher',output_kind='웹/API 근거 수집 시작')
    requested_keyword=keyword
    try:
        from dashboard.agents.synapse import research_query
        keyword=research_query(keyword,folder)
    except (OSError,ValueError,TypeError):pass
    sources=[]
    for candidate in search_urls(keyword)[:5]:
        try: body=public_text(candidate['url'])
        except (requests.RequestException,ValueError,OSError,KeyError):continue
        if len(body['text'])>=200:sources.append({**body,'title':candidate.get('title','')})
        if len(sources)>=3:break
    write(folder/'research.json',{'keyword':keyword,'requestedKeyword':requested_keyword,'sources':sources,'collectedAt':datetime.now(timezone.utc).isoformat()})
    (folder/'research.md').write_text('\n\n'.join(x['url']+'\n'+x['text'] for x in sources),encoding='utf-8')
    emit_work_event(actor='radar',actor_label='레이더',task_id=task,phase='completed',stage='researcher',output_kind=f'실제 본문 근거 {len(sources)}개 수집')
    return sources
