"""Shared account-scoped Google UI throttle state. No browser control or credentials."""
import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

PATH = Path(__file__).resolve().parent.parent / 'dashboard' / 'data' / 'gsc-ui-state.json'


def state(account):
    try:
        return json.loads(PATH.read_text(encoding='utf-8')).get('accounts',{}).get(account,{})
    except (OSError,ValueError,AttributeError):
        return {}


def paused(account,now=None):
    record=state(account)
    try:
        retry=datetime.fromisoformat(record['nextRetryAt'])
        return retry > (now or datetime.now(timezone.utc))
    except (KeyError,ValueError,TypeError):
        return False


def write_account(account,record):
    try:
        document=json.loads(PATH.read_text(encoding='utf-8'))
    except (OSError,ValueError):
        document={'accounts':{}}
    document.setdefault('accounts',{})[account]=record
    PATH.parent.mkdir(parents=True,exist_ok=True)
    handle,name=tempfile.mkstemp(dir=PATH.parent,prefix='.gsc-ui-',suffix='.tmp')
    try:
        with os.fdopen(handle,'w',encoding='utf-8') as stream:
            json.dump(document,stream,ensure_ascii=False)
        os.replace(name,PATH)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def mark_success(account,now=None):
    now=now or datetime.now(timezone.utc)
    if paused(account,now):
        return False
    record={**state(account),'status':'ready','lastSuccessAt':now.isoformat(),
            'consecutiveThrottles':0,'nextRetryAt':None}
    write_account(account,record)
    return True


def throttle(account,retry_after=None,now=None):
    now=now or datetime.now(timezone.utc)
    previous=state(account)
    failures=min(3,int(previous.get('consecutiveThrottles',0))+1)
    delay=timedelta(hours=min(24,6*2**(failures-1)))
    if retry_after:
        try:
            delay=timedelta(seconds=max(0,int(retry_after)))
        except (ValueError,TypeError):
            try:
                delay=max(timedelta(),parsedate_to_datetime(retry_after)-now)
            except (ValueError,TypeError,OverflowError):
                pass
    record={'status':'backoff','reason':'Google Search Console UI HTTP 429 · 계정 전체 조회 일시 중지',
            'lastAttemptAt':now.isoformat(),'lastFailureAt':now.isoformat(),
            'nextRetryAt':(now+delay).isoformat(),'consecutiveThrottles':failures,
            'source':'Google Search Console owner UI','account':account}
    write_account(account,record)
    return record


def check_response(account,response):
    if response and response.status==429:
        throttle(account,response.headers.get('retry-after'))
        raise ValueError('Google UI 계정 전체 429 대기')


def check_text(account,text):
    if '429.' in text:
        throttle(account)
        raise ValueError('Google UI 계정 전체 429 대기')
