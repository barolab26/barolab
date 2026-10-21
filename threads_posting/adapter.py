"""Official Threads API transport. No browser automation or implicit credentials.

Only submit_part writes externally; its caller owns durable attempt reservation.
Creating a container never sets auto_publish_text. No write is retried here.
"""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import time
from urllib.parse import urlsplit, urlencode

import requests
from common.codex_cli import is_wsl, to_wsl_path

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_ACCOUNT = 'mustpickinfo'
TIMEOUT = (5, 20)
DEFAULT_BASE = 'https://graph.threads.com/v1.0'
REQUIRED_SCOPES = frozenset(('threads_basic','threads_content_publish','threads_manage_insights','threads_manage_replies','threads_read_replies'))


class AdapterError(RuntimeError):
    def __init__(self, code, *, stage='preflight', uncertain=False, retryable=False):
        super().__init__(code)
        self.code, self.stage, self.uncertain, self.retryable = code, stage, uncertain, retryable


def stamp():
    return datetime.now(timezone.utc).isoformat()


def _published_time(value):
    try:
        parsed=datetime.fromisoformat(value.replace('Z','+00:00'))
        return parsed.astimezone(timezone.utc).isoformat() if parsed.tzinfo is not None else None
    except (TypeError,ValueError,AttributeError):return None


def _api(config):
    return config.get('api', {}) if isinstance(config.get('api', {}), dict) else {}


def _token(config):
    options = _api(config)
    env = options.get('token_env', 'THREADS_ACCESS_TOKEN')
    if not isinstance(env, str) or not re.fullmatch(r'THREADS_[A-Z0-9_]+', env):
        raise AdapterError('invalid_private_token_reference')
    value = os.environ.get(env)
    filename = options.get('token_file')
    if not value and filename:
        if is_wsl():
            filename = to_wsl_path(filename)
        path = Path(filename).expanduser().resolve()
        if any(path.is_relative_to((ROOT / directory).resolve()) for directory in ('dashboard','cf_posting','naver_blog_posting')):
            raise AdapterError('public_token_reference_forbidden')
        try:
            value = path.read_text(encoding='utf-8-sig').strip()
            if value.startswith('{'): value = json.loads(value).get('access_token')
        except (OSError, ValueError, AttributeError):
            raise AdapterError('needs_connection') from None
    if not isinstance(value, str) or not value.strip() or any(c.isspace() for c in value):
        raise AdapterError('needs_connection')
    return value


class Client:
    def __init__(self, config, *, token_override=None):
        if config.get('account_key',EXPECTED_ACCOUNT) != EXPECTED_ACCOUNT:
            raise AdapterError('unauthorized_account_configuration')
        self.token = _token(config) if token_override is None else token_override
        if not isinstance(self.token,str) or not self.token or any(c.isspace() for c in self.token):
            raise AdapterError('needs_connection')
        self.base = _api(config).get('base_url', DEFAULT_BASE).rstrip('/')
        parsed = urlsplit(self.base)
        if parsed.scheme != 'https' or parsed.netloc not in ('graph.threads.net', 'graph.threads.com') or not re.fullmatch(r'(?:/v\d+\.\d+)?', parsed.path) or parsed.query or parsed.fragment:
            raise AdapterError('invalid_official_api_base')

    def request(self, method, endpoint, params=None, *, stage='read'):
        from common.ego_telemetry import action
        with action('api_request', 'threads-api-read' if method == 'GET' else 'threads-api-write'):
            return self._request(method, endpoint, params, stage=stage)

    def _request(self, method, endpoint, params=None, *, stage='read'):
        if not re.fullmatch(r'(?:me|\d+)(?:/(?:threads|threads_publish|threads_publishing_limit|threads_insights|insights))?', endpoint) and not (endpoint=='debug_token' and method=='GET'):
            raise AdapterError('invalid_api_endpoint', stage=stage)
        try:
            response = requests.request(method, self.base + '/' + endpoint,
                params=params if method == 'GET' else None, data=params if method == 'POST' else None,
                headers={'Authorization': 'Bearer ' + self.token}, timeout=TIMEOUT,
                allow_redirects=False, verify=True)
        except requests.RequestException:
            raise AdapterError('api_transport_unavailable', stage=stage, retryable=stage != 'publish', uncertain=stage == 'publish') from None
        if response.status_code != 200:
            code = 'api_access_denied' if response.status_code in (401,403) else 'api_rate_limited' if response.status_code == 429 else 'api_http_error'
            raise AdapterError(code, stage=stage, retryable=response.status_code >= 500 and stage != 'publish', uncertain=stage == 'publish')
        try:
            value = response.json()
        except ValueError:
            raise AdapterError('api_response_invalid', stage=stage, uncertain=stage == 'publish') from None
        if not isinstance(value, dict) or 'error' in value:
            raise AdapterError('api_response_error', stage=stage, uncertain=stage == 'publish')
        return value


def _identity(client):
    user = client.request('GET', 'me', {'fields': 'id,username'})
    if not isinstance(user.get('username'),str) or user['username'].lower() != EXPECTED_ACCOUNT or not re.fullmatch(r'\d+', str(user.get('id', ''))):
        raise AdapterError('account_identity_mismatch')
    return user


def connection_status(config):
    result = {'connected': False, 'account_verified': False, 'account_key': EXPECTED_ACCOUNT,
              'reason': 'needs_connection', 'checked_at': stamp()}
    try:
        client = Client(config); _identity(client)
        result.update(connected=True, account_verified=True, reason=None)
    except AdapterError as exc:
        result['reason'] = exc.code
    result['authorization_requirements'] = authorization_requirements(config)
    return result


def readiness_status(config):
    """Read-only actual grants, expiry, token identity and quota. No app secret.

    A usable identity alone is connected, not publish-ready. No raw debug payload,
    token, request URL, file path, or provider exception text leaves this function.
    """
    result={'connected':False,'account_verified':False,'account_key':EXPECTED_ACCOUNT,
            'status':'needs_connection','reason':'needs_connection','checked_at':stamp(),
            'ready':False,'publishReady':False,'requiredScopes':sorted(REQUIRED_SCOPES),
            'grantedScopes':None,'missingScopes':None,'scopesStatus':'unknown',
            'expiresAt':None,'expiresAtUTC':None,'expiryStatus':'unknown','tokenUserMatches':None,
            'quotaStatus':'unknown','quota':None,'readinessIssues':[]}
    try:
        client=Client(config);user=_identity(client)
        result.update(connected=True,account_verified=True,status='readiness_incomplete',reason=None)
    except AdapterError as exc:
        result['reason']=exc.code;result['readinessIssues']=[exc.code];return result
    try:
        raw=client.request('GET','debug_token',{'input_token':client.token})
        data=raw.get('data')
        if not isinstance(data,dict):raise AdapterError('token_debug_response_unverified')
        token_user=data.get('user_id')
        if isinstance(token_user,(str,int)) and str(token_user).isdigit():result['tokenUserMatches']=str(token_user)==str(user['id'])
        scopes=data.get('scopes')
        if isinstance(scopes,list) and all(isinstance(scope,str) and re.fullmatch(r'[a-z][a-z0-9_]{1,127}',scope) for scope in scopes):
            result['grantedScopes']=sorted(set(scopes));result['missingScopes']=sorted(REQUIRED_SCOPES-set(scopes))
            result['scopesStatus']='verified' if not result['missingScopes'] else 'missing'
        expires=data.get('expires_at')
        if type(expires) is int and expires>0:
            try:
                expiry=datetime.fromtimestamp(expires,timezone.utc)
                result['expiresAtUTC']=expiry.isoformat();result['expiresAt']=expiry.isoformat()
                result['expiryStatus']='verified' if expiry>datetime.now(timezone.utc) else 'expired'
            except (ValueError,OverflowError,OSError):pass
        if data.get('is_valid') is False:result['readinessIssues'].append('token_reported_invalid')
    except AdapterError as exc:result['readinessIssues'].append(exc.code)
    try:
        report=client.request('GET','me/threads_publishing_limit',{'fields':'quota_usage,config,reply_quota_usage,reply_config'})
        rows=report.get('data')
        if not isinstance(rows,list) or len(rows)!=1 or not isinstance(rows[0],dict):raise AdapterError('publishing_quota_unverified')
        row=rows[0];quota={}
        for name,usage_key,config_key in [('posts','quota_usage','config'),('replies','reply_quota_usage','reply_config')]:
            policy=row.get(config_key);usage=row.get(usage_key);total=policy.get('quota_total') if isinstance(policy,dict) else None
            if type(usage) is int and type(total) is int and 0<=usage and total>0:
                quota[name]={'usage':usage,'limit':total,'remaining':max(0,total-usage)}
        result['quota']=quota or None
        if 'posts' in quota and (not config.get('maxFollowups',0) or 'replies' in quota):
            result['quotaStatus']='verified'
            if any(item['remaining']==0 for item in quota.values()):result['readinessIssues'].append('publishing_quota_exhausted')
    except AdapterError as exc:result['readinessIssues'].append(exc.code)
    if result['tokenUserMatches'] is not True:result['readinessIssues'].append('token_user_identity_unverified' if result['tokenUserMatches'] is None else 'token_user_identity_mismatch')
    if result['scopesStatus']!='verified':result['readinessIssues'].append('token_scopes_missing' if result['scopesStatus']=='missing' else 'token_scopes_unverified')
    if result['expiryStatus']!='verified':result['readinessIssues'].append('token_expired' if result['expiryStatus']=='expired' else 'token_expiry_unverified')
    if result['quotaStatus']!='verified':result['readinessIssues'].append('publishing_quota_unverified')
    result['readinessIssues']=list(dict.fromkeys(result['readinessIssues']))
    result['ready']=result['publishReady']=not result['readinessIssues']
    result['status']='ready' if result['ready'] else 'readiness_incomplete'
    result['reason']=None if result['ready'] else result['readinessIssues'][0]
    return result


def authorization_requirements(config):
    """Non-secret setup diagnostics; no app creation, consent or token generation."""
    options=config.get('oauth',{})
    app_id=os.environ.get(options.get('app_id_env','THREADS_APP_ID'),'')
    secret=os.environ.get(options.get('app_secret_env','THREADS_APP_SECRET'),'')
    redirect=options.get('redirect_uri')
    p=urlsplit(redirect or '')
    valid_redirect=p.scheme=='https' and bool(p.hostname) and p.hostname not in ('localhost','127.0.0.1','::1') and not p.username and not p.password and not p.fragment
    missing=[]
    if not re.fullmatch(r'\d+',app_id): missing.append('threads_meta_app_id_required')
    if not secret: missing.append('threads_meta_app_secret_required')
    if not valid_redirect: missing.append('registered_https_oauth_callback_required')
    return {'ready':not missing,'missing':missing,'account_key':EXPECTED_ACCOUNT,
            'requires_user_consent':True,'requires_registered_callback':True,
            'setup_scope':'optional_authorization_code_flow; an existing valid Threads user token can connect without a new callback server',
            'scopes':['threads_basic','threads_content_publish','threads_manage_insights'] + (['threads_manage_replies'] if config.get('maxFollowups',0) else [])}


def build_authorization_url(config,state):
    requirements=authorization_requirements(config)
    if not requirements['ready']: raise AdapterError('oauth_setup_incomplete')
    if not isinstance(state,str) or not re.fullmatch(r'[A-Za-z0-9_-]{32,200}',state): raise AdapterError('oauth_state_invalid')
    options=config.get('oauth',{})
    return 'https://www.threads.com/oauth/authorize?'+urlencode({'client_id':os.environ[options.get('app_id_env','THREADS_APP_ID')],
        'redirect_uri':options['redirect_uri'],'scope':','.join(requirements['scopes']),'response_type':'code','state':state})


def exchange_authorization_code(config,code):
    """Caller verifies/consumes OAuth state and stores result privately, never prints it."""
    if not authorization_requirements(config)['ready'] or not isinstance(code,str) or not code or len(code)>4096:
        raise AdapterError('oauth_setup_or_code_invalid')
    options=config.get('oauth',{});base=_api(config).get('base_url',DEFAULT_BASE).rstrip('/')
    p=urlsplit(base)
    if p.scheme!='https' or p.netloc not in ('graph.threads.net','graph.threads.com') or not re.fullmatch(r'(?:/v\d+\.\d+)?',p.path) or p.query or p.fragment:
        raise AdapterError('invalid_official_api_base')
    secret=os.environ[options.get('app_secret_env','THREADS_APP_SECRET')]
    try:
        short=requests.post(base+'/oauth/access_token',data={'client_id':os.environ[options.get('app_id_env','THREADS_APP_ID')],
            'client_secret':secret,'code':code,'grant_type':'authorization_code','redirect_uri':options['redirect_uri']},
            timeout=TIMEOUT,allow_redirects=False,verify=True)
        if short.status_code!=200: raise AdapterError('oauth_code_exchange_failed')
        short_value=short.json();token=short_value.get('access_token')
        if not isinstance(token,str) or not token: raise AdapterError('oauth_token_response_invalid')
        long=requests.get(base+'/access_token',params={'grant_type':'th_exchange_token','client_secret':secret},
            headers={'Authorization':'Bearer '+token},timeout=TIMEOUT,allow_redirects=False,verify=True)
        if long.status_code!=200: raise AdapterError('oauth_long_lived_exchange_failed')
        result=long.json()
        if not isinstance(result.get('access_token'),str) or type(result.get('expires_in')) is not int or result['expires_in']<=0:
            raise AdapterError('oauth_token_response_invalid')
        return {'access_token':result['access_token'],'expires_in':result['expires_in'],'created_at':stamp()}
    except (requests.RequestException,ValueError,AttributeError):
        raise AdapterError('oauth_transport_or_response_invalid') from None


def _quota(client, reply):
    report = client.request('GET', 'me/threads_publishing_limit', {'fields':'quota_usage,config,reply_quota_usage,reply_config'})
    rows = report.get('data')
    if not isinstance(rows, list) or len(rows) != 1: raise AdapterError('publishing_quota_unverified')
    row = rows[0]; usage = row.get('reply_quota_usage' if reply else 'quota_usage')
    policy = row.get('reply_config' if reply else 'config', {})
    total = policy.get('quota_total') if isinstance(policy, dict) else None
    if type(usage) is not int or type(total) is not int or usage < 0 or total <= 0:
        raise AdapterError('publishing_quota_unverified')
    if usage >= total: raise AdapterError('publishing_quota_exhausted')


def submit_part(config, part, before_submit):
    if not callable(before_submit): raise AdapterError('durable_submit_callback_required')
    text = part.get('text'); parent = part.get('parent_platform_id')
    if not isinstance(text, str) or not text.strip() or len(text) > 500:
        raise AdapterError('text_outside_supported_pilot_bounds')
    if part.get('kind') not in ('main', 'followup') or (part['kind'] == 'followup' and not re.fullmatch(r'\d+', str(parent or ''))):
        raise AdapterError('reply_parent_required')
    outbound = part.get('outbound_url')
    if outbound and (not isinstance(outbound, str) or outbound not in text or urlsplit(outbound).scheme != 'https'):
        raise AdapterError('exact_outbound_url_missing')
    client = Client(config); _identity(client); _quota(client, part['kind'] == 'followup')
    payload = {'media_type':'TEXT','text':text}
    if part['kind'] == 'followup': payload['reply_to_id'] = str(parent)
    container = client.request('POST','me/threads',payload,stage='create')
    cid = str(container.get('id', ''))
    if not re.fullmatch(r'\d+',cid): raise AdapterError('container_id_unavailable',stage='create')
    for poll in range(4):
        ready = client.request('GET',cid,{'fields':'status,error_message'})
        if ready.get('status') == 'FINISHED': break
        if ready.get('status') != 'IN_PROGRESS' or poll == 3:
            error=AdapterError('container_not_ready',stage='create',retryable=False)
            error.container_id=cid
            raise error
        time.sleep(1)
    before_submit()  # The caller must commit its attempt before this returns.
    published = client.request('POST','me/threads_publish',{'creation_id':cid},stage='publish')
    pid = str(published.get('id', ''))
    if not re.fullmatch(r'\d+',pid): raise AdapterError('publication_id_unavailable',stage='publish',uncertain=True)
    result = {'platform_id':pid,'permalink':None,'published_at':None,'reason':None}
    try:
        readback=client.request('GET',pid,{'fields':'permalink,timestamp'})
        result['permalink'] = _permalink(readback.get('permalink'))
        result['published_at'] = _published_time(readback.get('timestamp'))
        if not result['permalink']: result['reason'] = 'published_id_received_permalink_unverified'
        elif not result['published_at']:result['reason']='publication_time_unverified'
    except AdapterError:
        result['reason'] = 'published_id_received_permalink_unverified'
    return result


def _permalink(value):
    if not isinstance(value,str): return None
    parsed = urlsplit(value)
    if parsed.scheme == 'https' and parsed.netloc in ('www.threads.net','threads.net','www.threads.com','threads.com') and re.fullmatch(r'/@mustpickinfo/post/[A-Za-z0-9_-]+/?',parsed.path) and not parsed.query and not parsed.fragment:
        return value
    return None


def _normal(value):
    return ' '.join(value.replace('\u200b','').split()) if isinstance(value,str) else ''


def recover_unknown(config,part):
    """Read at most 2x25 own posts. Never publish or infer from a partial inventory."""
    result={'matched':False,'platform_id':None,'permalink':None,'published_at':None,'reason':'recovery_unverified'}
    text=part.get('text');outbound=part.get('outbound_url');intent=_published_time(part.get('intent_at'))
    if part.get('account_key')!=EXPECTED_ACCOUNT or not isinstance(text,str) or not intent:
        return {**result,'reason':'recovery_identity_or_intent_missing'}
    if hashlib.sha256(text.encode()).hexdigest()!=part.get('text_sha256'):
        return {**result,'reason':'recovery_ledger_text_mismatch'}
    if not isinstance(outbound,str) or text.count(outbound)!=1:
        return {**result,'reason':'recovery_unique_utm_required'}
    from urllib.parse import parse_qs
    parsed=urlsplit(outbound);query=parse_qs(parsed.query)
    if parsed.scheme!='https' or any(query.get(k)!=[v] for k,v in [('utm_source','threads'),('utm_medium','social'),('utm_campaign','cf_bridge')]) or len(query.get('utm_content',[]))!=1 or not query['utm_content'][0]:
        return {**result,'reason':'recovery_unique_utm_required'}
    try:
        client=Client(config);_identity(client);matches={};after=None;complete=False;seen=set();read=0
        for page in range(2):
            params={'fields':'id,text,username,permalink,timestamp','limit':25,'since':int(datetime.fromisoformat(intent).timestamp())}
            if after:params['after']=after
            report=client.request('GET','me/threads',params)
            rows=report.get('data')
            if not isinstance(rows,list) or len(rows)>25:raise AdapterError('recovery_inventory_unverified')
            read+=len(rows)
            for row in rows:
                if not isinstance(row,dict):raise AdapterError('recovery_inventory_unverified')
                actual=row.get('text');published=_published_time(row.get('timestamp'));pid=str(row.get('id',''))
                if row.get('username')!=EXPECTED_ACCOUNT or actual!=text or not published or datetime.fromisoformat(published)<datetime.fromisoformat(intent):continue
                if not re.fullmatch(r'\d+',pid) or actual.count(outbound)!=1 or not _permalink(row.get('permalink')):continue
                matches[pid]={'platform_id':pid,'permalink':row['permalink'],'published_at':published}
            paging=report.get('paging',{})
            if not isinstance(paging,dict):raise AdapterError('recovery_inventory_unverified')
            cursors=paging.get('cursors') or {}
            if not isinstance(cursors,dict):raise AdapterError('recovery_inventory_unverified')
            next_after=cursors.get('after') if paging.get('next') else None
            if not paging.get('next'):complete=True;break
            if not isinstance(next_after,str) or not re.fullmatch(r'[A-Za-z0-9_=-]{1,2048}',next_after) or next_after in seen:break
            seen.add(next_after);after=next_after
        if not complete:return {**result,'reason':'recovery_inventory_incomplete'}
        if len(matches)!=1:return {**result,'reason':'recovery_no_match' if not matches else 'recovery_ambiguous_matches'}
        matched=next(iter(matches.values()))
        return {**result,**matched,'matched':True,'match_count':1,'account_key':EXPECTED_ACCOUNT,
            'text_sha256':part['text_sha256'],'outbound_url':outbound,'reason':None,'evidence':{
            'account_verified':True,'exact_text_sha256':part['text_sha256'],'exact_text_equal':True,
            'unique_outbound_url_once':True,'after_intent':True,'returned_posts':read,
            'inventory_complete':True,'checked_at':stamp()}}
    except AdapterError as exc:return {**result,'reason':exc.code}


def verify_public(config, part, result):
    expected = part.get('text', ''); pid = str(result.get('platform_id', ''))
    evidence = {'verified':False,'public':False,'account_key':EXPECTED_ACCOUNT,'platform_id':pid,
                'text_sha256':hashlib.sha256(expected.encode()).hexdigest(),'outbound_url':part.get('outbound_url'),
                'permalink':None,'checked_at':stamp(),'reason':'publication_unverified'}
    evidence['published_at']=None
    try:
        if not re.fullmatch(r'\d+',pid): raise AdapterError('publication_id_unavailable')
        client = Client(config); _identity(client)
        actual = client.request('GET',pid,{'fields':'id,username,text,permalink,timestamp,link_attachment_url,is_reply,replied_to'})
        permalink = _permalink(actual.get('permalink')); evidence['permalink'] = permalink
        if str(actual.get('id')) != pid or actual.get('username','').lower() != EXPECTED_ACCOUNT or _normal(actual.get('text')) != _normal(expected) or not permalink:
            raise AdapterError('publication_readback_mismatch')
        evidence['published_at']=_published_time(actual.get('timestamp'))
        if part.get('outbound_url') and part['outbound_url'] not in actual.get('text',''):
            raise AdapterError('outbound_readback_mismatch')
        if part.get('kind') == 'followup' and (not actual.get('is_reply') or str((actual.get('replied_to') or {}).get('id')) != str(part.get('parent_platform_id'))):
            raise AdapterError('reply_parent_readback_mismatch')
        response = requests.get(permalink,timeout=TIMEOUT,allow_redirects=False,verify=True,headers={'User-Agent':'Mozilla/5.0'})
        if response.status_code != 200 or len(response.content) > 2_000_000:
            raise AdapterError('anonymous_public_read_unavailable')
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(response.text,'html.parser')
        for tag in soup.select('script,style,noscript'): tag.decompose()
        visible = _normal(soup.get_text(' '))
        if not _normal(expected) or _normal(expected) not in visible:
            raise AdapterError('anonymous_public_body_unmatched')
        evidence.update(verified=True,public=True,reason=None)
    except AdapterError as exc:
        evidence['reason'] = exc.code
    except requests.RequestException:
        evidence['reason'] = 'anonymous_public_read_unavailable'
    return evidence
