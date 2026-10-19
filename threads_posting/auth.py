"""Single-use loopback token import. No public service, OAuth grant or publication.

The operator obtains a token in Meta's own UI and fills a masked local form.
Only an exact @mustpickinfo API identity can be stored. Never print token values.
"""
import argparse
import hmac
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import secrets
import subprocess
import time
import uuid
from urllib.parse import parse_qs

from .adapter import Client, AdapterError, EXPECTED_ACCOUNT, ROOT, _identity, stamp
from common.dashboard_jobs import write

TOKEN_PATH = Path.home()/'.barolab/secrets/threads-mustpickinfo.json'
MAX_BODY = 16384


def _harden_private_acl(path):
    if os.name!='nt':os.chmod(path,0o600);return
    import csv,re
    flags=getattr(subprocess,'CREATE_NO_WINDOW',0)
    who=subprocess.run(['whoami.exe','/user','/fo','csv','/nh'],capture_output=True,text=True,timeout=10,creationflags=flags)
    rows=list(csv.reader(who.stdout.splitlines()))
    sid=rows[0][1] if who.returncode==0 and rows and len(rows[0])>=2 else ''
    if not re.fullmatch(r'S-1-[0-9-]+',sid):raise OSError('Private ACL identity unavailable')
    command=[str(Path(os.environ.get('WINDIR','C:/Windows'))/'System32/icacls.exe'),str(path),'/inheritance:r','/grant:r',
             '*'+sid+':(F)','*S-1-5-18:(F)','*S-1-5-32-544:(F)']
    changed=subprocess.run(command,capture_output=True,timeout=10,creationflags=flags)
    if changed.returncode:raise OSError('Private ACL hardening failed')


def save_private_token(token,token_path=None):
    """Protect an empty temporary file before writing secrets, then atomic replace."""
    target=Path(token_path or TOKEN_PATH).resolve()
    if any(target.is_relative_to((ROOT/directory).resolve()) for directory in ('dashboard','cf_posting','naver_blog_posting')):
        raise ValueError('Public token storage forbidden')
    target.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    temporary=target.with_name(target.name+'.'+uuid.uuid4().hex+'.tmp')
    try:
        descriptor=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600);os.close(descriptor)
        _harden_private_acl(temporary)
        with temporary.open('w',encoding='utf-8') as stream:
            json.dump({'access_token':token,'account_key':EXPECTED_ACCOUNT,'imported_at':stamp()},stream)
            stream.flush();os.fsync(stream.fileno())
        os.replace(temporary,target)
    finally:temporary.unlink(missing_ok=True)


class Receiver:
    def __init__(self, config, *, ttl_seconds=600, token_path=TOKEN_PATH):
        if not 30 <= ttl_seconds <= 600: raise ValueError('Token receiver TTL must be 30-600 seconds')
        self.config=config; self.deadline=time.monotonic()+ttl_seconds
        self.path='/import/'+secrets.token_urlsafe(32);self.csrf=secrets.token_urlsafe(32)
        self.token_path=Path(token_path).resolve();self.done=False
        if any(self.token_path.is_relative_to((ROOT/directory).resolve()) for directory in ('dashboard','cf_posting','naver_blog_posting')):
            raise ValueError('Token storage must not be under a public static mount')
        self.result={'connected':False,'account_verified':False,'account_key':EXPECTED_ACCOUNT,'reason':'local_import_timeout','checked_at':stamp()}
        self.server=HTTPServer(('127.0.0.1',0),self.handler())
        self.server.timeout=1
        self.origin='http://127.0.0.1:'+str(self.server.server_port)
        self.host='127.0.0.1:'+str(self.server.server_port)
        self.url=self.origin+self.path

    def handler(self):
        owner=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass

            def setup(self):
                super().setup();self.connection.settimeout(3)

            def reply(self,status,body):
                payload=body.encode('utf-8');self.send_response(status)
                for key,value in [('Content-Type','text/html; charset=utf-8'),('Cache-Control','no-store'),
                    ('Content-Security-Policy',"default-src 'none'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'"),
                    ('Referrer-Policy','no-referrer'),('X-Content-Type-Options','nosniff'),('Content-Length',str(len(payload))),('Connection','close')]:self.send_header(key,value)
                self.end_headers();self.wfile.write(payload)

            def valid_path(self):
                if owner.done or time.monotonic()>owner.deadline:self.reply(410,'Import session expired.');return False
                if self.headers.get('Host')!=owner.host or self.path!=owner.path:self.reply(404,'Not found.');return False
                return True

            def do_GET(self):
                if not self.valid_path():return
                self.reply(200,'<!doctype html><html lang="ko"><meta charset="utf-8"><title>Threads 로컬 연결</title>'
                    '<h1>@mustpickinfo API 연결</h1><p>Meta에서 발급한 사용자 토큰을 가져옵니다. 계정 확인 후 이 창은 종료됩니다.</p>'
                    '<form method="post" action="'+owner.path+'" autocomplete="off">'
                    '<input type="hidden" name="state" value="'+owner.csrf+'">'
                    '<label>사용자 토큰 <input name="token" type="password" autocomplete="off" required maxlength="8192"></label>'
                    '<button type="submit">계정 확인 후 연결</button></form></html>')

            def do_POST(self):
                if not self.valid_path():return
                if self.headers.get('Origin')!=owner.origin:self.reply(403,'Origin rejected.');return
                if self.headers.get('Content-Type','').split(';')[0].strip()!='application/x-www-form-urlencoded':self.reply(415,'Form required.');return
                try:length=int(self.headers.get('Content-Length','0'))
                except ValueError:self.reply(400,'Invalid request.');return
                if not 1<=length<=MAX_BODY:self.reply(413,'Request too large.');return
                try:fields=parse_qs(self.rfile.read(length).decode('utf-8'),strict_parsing=True)
                except (ValueError,UnicodeError,TimeoutError):self.reply(400,'Invalid form.');return
                if set(fields)!={'token','state'} or len(fields['state'])!=1 or len(fields['token'])!=1 or not hmac.compare_digest(fields['state'][0],owner.csrf):
                    self.reply(403,'State rejected.');return
                token=fields['token'][0]
                owner.done=True  # A valid form consumes this capability, even on API failure.
                if not token or len(token)>8192 or any(c.isspace() for c in token):
                    owner.result['reason']='invalid_token_format';self.reply(400,'Token format rejected.');return
                try:
                    client=Client(owner.config,token_override=token);_identity(client)
                    save_private_token(token,owner.token_path)
                    owner.result.update(connected=True,account_verified=True,reason=None,token_file=str(owner.token_path),checked_at=stamp())
                    self.reply(200,'<!doctype html><meta charset="utf-8"><p>@mustpickinfo 계정 확인 및 연결 완료. 이 창을 닫으셔도 됩니다.</p>')
                except AdapterError as exc:
                    owner.result.update(reason=exc.code,checked_at=stamp());self.reply(400,'API account verification failed. No token was saved.')
                except OSError:
                    owner.result.update(reason='private_token_storage_failed',checked_at=stamp());self.reply(500,'Private storage failed.')
        return Handler

    def serve(self):
        try:
            while not self.done and time.monotonic()<=self.deadline:self.server.handle_request()
        finally:self.server.server_close()
        return self.result


def receive_token(config,ttl_seconds=600):
    receiver=Receiver(config,ttl_seconds=ttl_seconds)
    print(json.dumps({'local_import_url':receiver.url,'expires_in_seconds':ttl_seconds}),flush=True)
    return receiver.serve()


def import_private_token(temp_path=None, *, verify_readiness=False):
    """Consume the approved private handoff file; return only redacted status.

    This alternative to the local form performs no OAuth grant or publication.
    The handoff is removed even if identity validation or persistence fails.
    """
    from .config import load,save
    from .adapter import readiness_status
    path=Path(temp_path or Path.home()/'.barolab/secrets/threads-mustpickinfo-import.tmp').resolve()
    approved=(Path.home()/'.barolab/secrets/threads-mustpickinfo-import.tmp').resolve()
    if path!=approved:raise ValueError('Only the approved private handoff file can be imported')
    result={'connected':False,'account_verified':False,'account_key':EXPECTED_ACCOUNT,'reason':'private_import_failed','checked_at':stamp()}
    try:
        if path.stat().st_size>8192:raise AdapterError('invalid_token_format')
        token=path.read_text(encoding='utf-8').strip()
        config=load();client=Client(config,token_override=token);_identity(client)
        save_private_token(token)
        result.update(connected=True,account_verified=True,reason=None,checked_at=stamp())
        config['api']['token_file']=str(TOKEN_PATH);config['connection']=result;save(config)
        if verify_readiness:
            result=readiness_status(config);config['connection']=result;save(config)
        from .pipeline import snapshot
        snapshot(config)
    except AdapterError as exc:result['reason']=exc.code
    except (OSError,ValueError):result['reason']='private_import_storage_or_format_failed'
    finally:path.unlink(missing_ok=True)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--receive-token',action='store_true',required=True)
    parser.add_argument('--ttl-seconds',type=int,default=600);args=parser.parse_args()
    from .config import load,save
    config=load();result=receive_token(config,args.ttl_seconds)
    if result.get('connected'):
        config['api']['token_file']=result['token_file']
        config['connection']={key:value for key,value in result.items() if key!='token_file'};save(config)
    print(json.dumps({key:value for key,value in result.items() if key!='token_file'},ensure_ascii=False),flush=True)


if __name__=='__main__':main()
