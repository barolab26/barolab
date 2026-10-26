"""Bounded read-only cockpit probes. Never starts a browser or generates model text."""
import datetime as dt
import json
import math
import os
from pathlib import Path
import queue
import re
import subprocess
import tempfile
import threading
import time
from urllib.parse import urlsplit, urlunsplit
from concurrent.futures import ThreadPoolExecutor

import requests

ROOT=Path(__file__).resolve().parents[2]
FLEET=((9334,'soultin','mustpickinfo','정책·지원금·연금 / 블로그 1호'),
       (9333,'soul5373','mustinfo','연예이슈 / 애드포스트 · JEV 콘솔(04세션)'),
       (9335,'yoon_master','yoonviews','쇼핑커넥트 / 가전·리빙'),
       (9231,'adinfo0905','adinfo0905','직장인 루틴 / 지식iN 1호'),
       (9230,'stone0747','stone0747','지원금 마감 / 지식iN 2호'),
       (9440,'cf-flow','CF/Flow','CF 발행 / 공식 캡처 / 시각자료'),
       (9450,'threads','mustpickinfo','Threads 전용 작업 세션'))


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
                        'expression':'''(() => { const b=document.querySelector('#answerRegisterButton'); const text=document.querySelector('.se-canvas')?.textContent || ''; return {active:document.visibilityState === 'visible',questionId:location.hostname==='kin.naver.com' ? new URL(location.href).searchParams.get('docId') : null,editorHasContent:text.trim().length>0,editorCharCount:text.trim().length,registerPresent:!!b,registerEnabled:!!b && !b.disabled && b.getAttribute('aria-disabled')!=='true',captchaVisible:[...document.querySelectorAll('iframe[src*=\"/recaptcha/\"][src*=\"/bframe\"], #captcha, .captcha_wrap, .u_captcha')].some(e=>e.checkVisibility({checkOpacity:true,checkVisibilityCSS:true}) && e.getBoundingClientRect().width>0 && e.getBoundingClientRect().height>0)}; })()''','returnByValue':True}}))
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


def _jev_console_probe(ports=(9333, 9334, 9335, 9440)):
    """Read live JEV (TypeSafe) balance and token usage from the logged-in Chrome console tab."""
    import websocket
    for port in ports:
        try:
            r = requests.get(f'http://127.0.0.1:{port}/json/list', timeout=0.4, allow_redirects=False)
            if r.status_code != 200:
                continue
            tabs = r.json()
            tab = next((t for t in tabs if t.get('type') == 'page' and 'console.typesafe.ai' in str(t.get('url', ''))), None)
            if not tab or not tab.get('webSocketDebuggerUrl'):
                continue
            ws = websocket.create_connection(tab['webSocketDebuggerUrl'], timeout=0.8, suppress_origin=True)
            try:
                ws.send(json.dumps({'id': 1, 'method': 'Runtime.evaluate', 'params': {'expression': 'document.body ? document.body.innerText : ""', 'returnByValue': True}}))
                for _ in range(4):
                    msg = json.loads(ws.recv())
                    if msg.get('id') == 1:
                        text = str(msg.get('result', {}).get('result', {}).get('value') or '')
                        m_bal = re.search(r'Balance\s*\$([0-9]+(?:\.[0-9]+)?)', text, re.I)
                        m_tok = re.search(r'Tokens\s*([0-9.,]+[KMB]?)', text, re.I)
                        if m_bal:
                            bal = float(m_bal.group(1))
                            return {
                                'status': 'collected',
                                'balance': bal,
                                'unit': 'USD',
                                'tokensUsed': m_tok.group(1) if m_tok else None,
                                'sessionPort': port,
                                'sessionLabel': '04번 크롬' if port == 9333 else f'{port}번 크롬',
                                'source': str(tab.get('url', 'https://console.typesafe.ai/home')),
                            }
                        break
            finally:
                ws.close()
        except Exception:
            continue
    return None


def provider_credit_probe(provider, values):
    """Read balances only; a missing observation never becomes zero."""
    checked = time.time()
    names = {'kie': ('KIE_API_KEY',), 'jev': ('TYPESAFE_API_KEY', 'JEV_BAROINCOME_API_KEY')}
    key = next((values.get(name) for name in names[provider] if values.get(name)), None)
    out = dict(status='키 미설정', balance=None, checkedAt=checked, unit='credits')
    if provider == 'jev':
        console_data = _jev_console_probe()
        if console_data:
            return {**out, **console_data, 'usable': bool(key or console_data.get('balance', 0) > 0), 'apiKeySet': bool(key), 'checkedAt': checked}
        if not key:
            return out
        return {**out, 'status': '잔액 미수집 · 콘솔 로그인 필요', 'usable': bool(key), 'apiKeySet': bool(key),
                'source': 'https://help.typesafe.ai/articles/5505198974-what-s-a-402-error-and-how-can-i-add-more-credits'}
    if not key:
        return out
    try:
        response = requests.get('https://api.kie.ai/api/v1/chat/credit',
            headers={'Authorization': 'Bearer ' + key}, timeout=(3, 5), allow_redirects=False)
        if response.status_code != 200:
            return {**out, 'status': 'HTTP ' + str(response.status_code)}
        data = response.json()
        value = data.get('data')
        if data.get('code') != 200 or type(value) not in (int, float) or not math.isfinite(value) or value < 0:
            return {**out, 'status': '잔액 응답 미확인'}
        return {**out, 'status': 'collected', 'balance': value,
                'source': 'https://api.kie.ai/api/v1/chat/credit'}
    except (requests.RequestException, ValueError, TypeError, AttributeError):
        return {**out, 'status': '잔액 조회 지연'}


def _parse_agy_usage_output(stdout_text):
    payload = json.loads(stdout_text)
    if payload.get('status') != 'SUCCESS' or payload.get('command', {}).get('name') != 'usage':
        raise ValueError('Not a quota command result')
    groups = []
    for group in payload['command']['data']['groups'][:12]:
        name = group['name']
        if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9 +/()._-]{1,60}', name):
            raise ValueError('Invalid quota group')
        buckets = []
        for bucket in group['buckets'][:8]:
            fraction = bucket['remaining_fraction']
            window = bucket['window']
            reset = bucket['reset_time']
            if type(fraction) not in (int, float) or not math.isfinite(fraction) or not 0 <= fraction <= 1:
                raise ValueError('Invalid quota fraction')
            parsed = dt.datetime.fromisoformat(reset.replace('Z', '+00:00'))
            if parsed.tzinfo is None or window not in ('weekly', '5h'):
                raise ValueError('Invalid quota window')
            buckets.append(dict(window=window, remainingPercent=round(fraction * 100, 1), resetAt=parsed.isoformat()))
        if not buckets:
            raise ValueError('Missing quota buckets')
        groups.append(dict(name=name, buckets=buckets))
    if not groups:
        raise ValueError('Missing quota groups')
    return groups


def agy_quota():
    """Only the built-in /usage command across all configured Gemini accounts."""
    executable = Path.home() / '.local/bin/agy'
    if not executable.is_file():
        return dict(status='CLI 미설치', checkedAt=time.time())
    from common.agy_cli import list_account_homes, rotation_state
    homes = list_account_homes()
    rot = rotation_state()
    call_counts = rot.get('callCounts') or {}
    last_used = rot.get('lastUsedAccount')
    account_rows = []
    primary_groups = []
    for email, home_dir in homes:
        env = {**os.environ, 'HOME': str(home_dir), 'USERPROFILE': str(home_dir)}
        try:
            with tempfile.TemporaryDirectory(prefix='barolab-agy-quota-') as folder:
                result = subprocess.run([str(executable), '-p', '/usage', '--output-format', 'json', '--print-timeout', '15s'],
                    cwd=folder, env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True, encoding='utf-8', timeout=20)
            if result.returncode:
                account_rows.append(dict(email=email, status='조회 실패 · 로그인 확인', usable=False, checkedAt=time.time()))
                continue
            groups = _parse_agy_usage_output(result.stdout)
            if not primary_groups:
                primary_groups = groups
            account_rows.append(dict(
                email=email,
                status='collected',
                usable=True,
                activeRotation=True,
                isLastUsed=(email == last_used),
                callCount=int(call_counts.get(email, 0)),
                groups=groups,
                checkedAt=time.time(),
            ))
        except (OSError, ValueError, TypeError, KeyError, AttributeError, subprocess.SubprocessError):
            account_rows.append(dict(email=email, status='조회 지연 · 로그인 확인', usable=False, checkedAt=time.time()))
    if primary_groups:
        return dict(status='collected', groups=primary_groups, accounts=account_rows, lastUsedAccount=last_used, checkedAt=time.time())
    return dict(status='조회 지연 · CLI 로그인 확인', accounts=account_rows, checkedAt=time.time())


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
                    cf=pool.submit(credit_probe,values);cq=pool.submit(codex_quota);aq=pool.submit(agy_quota)
                    kp=pool.submit(provider_credit_probe,'kie',values);jp=pool.submit(provider_credit_probe,'jev',values)
                    credit=cf.result()
                    try:quota=cq.result()
                    except (OSError,RuntimeError,ValueError,KeyError,queue.Empty,subprocess.SubprocessError):quota=dict(status='조회 연결 대기',checkedAt=time.time())
                    agy=aq.result()
                    with self.lock:self.data={**self.data,'openrouter':credit,'codexQuota':quota,'agy':agy,'kie':kp.result(),'jev':jp.result()}
                    credits_at=time.monotonic()
                self.stop.wait(5)
    def start(self):
        self.thread=threading.Thread(target=self.run,name='cockpit-remote',daemon=True);self.thread.start()
    def get(self):
        with self.lock:return dict(self.data)
