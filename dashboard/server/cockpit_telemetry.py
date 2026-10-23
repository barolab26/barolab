"""Bounded read-only cockpit probes. Never starts a browser or generates model text."""
import datetime as dt
import json
import math
import os
from pathlib import Path
import queue
import re
import subprocess
import threading
import time
from urllib.parse import urlsplit, urlunsplit
from concurrent.futures import ThreadPoolExecutor

import requests

ROOT=Path(__file__).resolve().parents[2]
FLEET=((9334,'soultin','mustpickinfo','정책·지원금·연금 / 블로그 1호'),
       (9333,'soul5373','mustinfo','연예이슈 / 애드포스트 수집'),
       (9335,'yoon_master','yoonviews','쇼핑커넥트 / 가전·리빙'),
       (9231,'adinfo0905','adinfo0905','직장인 루틴 / 지식iN 1호'),
       (9230,'stone0747','stone0747','지원금 마감 / 지식iN 2호'),
       (9440,'cf-flow','CF/Flow','CF 발행 / 공식 캡처 / 시각자료'))


def env_values(root=ROOT):
    # Never execute .env content or expose it in snapshots.
    from dotenv import dotenv_values
    result={}
    for name in ('.env','.env','.env'):
        result.update({k:v for k,v in dotenv_values(Path(root)/name).items() if v is not None})
    result.update(os.environ);return result


def safe_url(value):
    try:
        u=urlsplit(value)
        if u.scheme not in ('http','https'):return u.scheme or '로컬'
        return urlunsplit((u.scheme,u.hostname or '',u.path,'',''))[:110]
    except ValueError:return ''


def fleet_probe(spec,hosts=('127.0.0.1',)):
    port,account,blog,purpose=spec
    from common.ubuntu_naver_browser import account_paths
    _,profile,_=account_paths(port)
    row=dict(port=port,account=account,blog=blog,profile=profile.name,purpose=purpose,online=False,tabs=[],selection='열린 탭')
    for host in hosts:
        try:
            r=requests.get(f'http://{host}:{port}/json/list',timeout=.3,allow_redirects=False)
            r.raise_for_status();tabs=r.json()
            if not isinstance(tabs,list):continue
            row.update(online=True,tabs=[dict(id=str(t.get('id',''))[:100],title=re.sub(r'[\x00-\x1f\x7f]',' ',str(t.get('title','')))[:120],
                url=safe_url(str(t.get('url','')))) for t in tabs[:64] if t.get('type')=='page'])
            import websocket
            for tab,raw in zip(row['tabs'],[t for t in tabs[:64] if t.get('type')=='page']):
                target=raw.get('webSocketDebuggerUrl','')
                if not target:continue
                ws=None
                try:
                    u=urlsplit(target)
                    if u.scheme!='ws' or u.hostname not in (host,'127.0.0.1','localhost'):continue
                    ws=websocket.create_connection(target,timeout=.3,suppress_origin=True)
                    ws.send(json.dumps({'id':1,'method':'Runtime.evaluate','params':{
                        'expression':'''(() => { const b=document.querySelector('#answerRegisterButton'); const text=document.querySelector('.se-canvas')?.textContent || ''; return {active:document.visibilityState === 'visible',questionId:location.hostname==='kin.naver.com' ? new URL(location.href).searchParams.get('docId') : null,editorHasContent:text.trim().length>0,editorCharCount:text.trim().length,registerPresent:!!b,registerEnabled:!!b && !b.disabled && b.getAttribute('aria-disabled')!=='true',captchaVisible:[...document.querySelectorAll('iframe[src*=captcha], #captcha, .captcha_wrap, .u_captcha')].some(e=>e.getClientRects().length>0)}; })()''','returnByValue':True}}))
                    for _ in range(4):
                        answer=json.loads(ws.recv())
                        if answer.get('id')==1:
                            value=answer.get('result',{}).get('result',{}).get('value')
                            if isinstance(value,dict):tab.update({k:value[k] for k in ('active','questionId','editorHasContent','editorCharCount','registerPresent','registerEnabled','captchaVisible') if k in value})
                            else:tab['active']=value is True
                            break
                except (OSError,ValueError,websocket.WebSocketException):pass
                finally:
                    if ws:ws.close()
            row['selection']='활성 탭' if any(t.get('active') for t in row['tabs']) else '열린 탭'
            return row
        except (requests.RequestException,ValueError,TypeError,AttributeError):continue
    return row


def codex_quota():
    from common.codex_cli import local_config,environment
    config=local_config();exe=config.get('wsl_executable') or config['executable']
    process=subprocess.Popen([exe,'app-server'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
        text=True,encoding='utf-8',env=environment(config),creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    incoming=queue.Queue(maxsize=64)
    def read():
        try:
            for line in process.stdout:
                if len(line)<200000:
                    try:incoming.put_nowait(json.loads(line))
                    except (ValueError,queue.Full):pass
        except (OSError,ValueError):pass
    thread=threading.Thread(target=read,daemon=True);thread.start();deadline=time.monotonic()+12
    def rpc(identifier,method,params=None):
        message=dict(id=identifier,method=method)
        if params is not None:message['params']=params
        process.stdin.write(json.dumps(message)+'\n');process.stdin.flush()
        while time.monotonic()<deadline:
            obj=incoming.get(timeout=max(.01,deadline-time.monotonic()))
            if obj.get('id')==identifier:
                if 'error' in obj:raise ValueError('quota response rejected')
                return obj['result']
        raise TimeoutError()
    try:
        rpc(1,'initialize',{'clientInfo':{'name':'barolab-monitor','version':'1.0'}})
        process.stdin.write('{"method":"initialized"}\n');process.stdin.flush()
        data=rpc(2,'account/rateLimits/read')
        buckets=data.get('rateLimitsByLimitId') or {'codex':data.get('rateLimits') or {}}
        safe={}
        for name,row in list(buckets.items())[:12]:
            safe[name]={k:{n:w.get(n) for n in ('usedPercent','windowDurationMins','resetsAt')} for k in ('primary','secondary')
                        if isinstance((w:=row.get(k)),dict)}
            credits=row.get('credits')
            if isinstance(credits,dict):
                safe[name]['credits']={k:credits.get(k) for k in ('hasCredits','unlimited','balance')}
            if row.get('planType'):safe[name]['planType']=str(row['planType'])[:30]
        return dict(status='collected',buckets=safe,checkedAt=time.time())
    finally:
        # Only this short-lived telemetry child; never a pipeline or browser.
        process.stdin.close()
        try:process.wait(timeout=1)
        except subprocess.TimeoutExpired:process.terminate();process.wait(timeout=2)
        thread.join(timeout=.2)


def credit_probe(values):
    key=values.get('OPENROUTER_API_KEY') or values.get('OPENROUTER_KEY')
    if not key:return dict(status='키 미설정',checkedAt=time.time())
    try:
        headers={'Authorization':'Bearer '+key}
        response=requests.get('https://openrouter.ai/api/v1/key',headers=headers,timeout=5,allow_redirects=False)
        if response.status_code in (404,405):response=requests.get('https://openrouter.ai/api/v1/auth/key',headers=headers,timeout=5,allow_redirects=False)
        if response.status_code!=200:return dict(status='HTTP '+str(response.status_code),checkedAt=time.time())
        data=response.json()['data'];out=dict(status='collected',checkedAt=time.time())
        for name in ('usage','usage_daily','limit','limit_remaining'):
            value=data.get(name);out[name]=value if isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value) else None
        # Key cap and account balance are distinct; never substitute one for the other.
        credits=requests.get('https://openrouter.ai/api/v1/credits',headers=headers,timeout=5,allow_redirects=False)
        if credits.status_code==200:
            c=credits.json().get('data',{})
            if all(isinstance(c.get(k),(int,float)) for k in ('total_credits','total_usage')):
                out['balance']=c['total_credits']-c['total_usage']
        return out
    except (requests.RequestException,ValueError,KeyError,TypeError):return dict(status='연결 지연',checkedAt=time.time())


class RemoteTelemetry:
    def __init__(self,root=ROOT,hosts=('127.0.0.1',)):
        self.root=root;self.hosts=hosts;self.stop=threading.Event();self.lock=threading.Lock();self.data={};self.thread=None
    def run(self):
        credits_at=0
        with ThreadPoolExecutor(max_workers=6,thread_name_prefix='cockpit-probe') as pool:
            while not self.stop.is_set():
                fleet=list(pool.map(lambda row:fleet_probe(row,self.hosts),FLEET))
                with self.lock:self.data={**self.data,'fleet':fleet}
                if time.monotonic()-credits_at>=60:
                    try:values=env_values(self.root)
                    except (OSError,ImportError):values=dict(os.environ)
                    cf=pool.submit(credit_probe,values);cq=pool.submit(codex_quota)
                    credit=cf.result()
                    try:quota=cq.result()
                    except (OSError,RuntimeError,ValueError,KeyError,queue.Empty,subprocess.SubprocessError):quota=dict(status='조회 연결 대기',checkedAt=time.time())
                    with self.lock:self.data={**self.data,'openrouter':credit,'codexQuota':quota}
                    credits_at=time.monotonic()
                self.stop.wait(5)
    def start(self):
        self.thread=threading.Thread(target=self.run,name='cockpit-remote',daemon=True);self.thread.start()
    def get(self):
        with self.lock:return dict(self.data)
