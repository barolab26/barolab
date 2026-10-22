"""Bounded search discovery; snippets never become article evidence."""
import os
from urllib.parse import urlsplit
import requests
from bs4 import BeautifulSoup


def search_urls(query):
    from dotenv import load_dotenv
    from pathlib import Path
    load_dotenv(Path(__file__).resolve().parents[1]/'cf_posting/.env')
    from common.public_capture import public_https_url
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
