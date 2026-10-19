from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
import re

from common.dashboard_jobs import write
from common.channel_attribution import PRIORITY_CF_DOMAINS

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = ROOT / 'server/data'
CONFIG = PRIVATE / 'threads-automation.json'
DB = PRIVATE / 'threads.sqlite3'
PUBLIC = ROOT / 'dashboard/data/threads.json'
CF_DOMAINS_16 = PRIORITY_CF_DOMAINS + ( 'baronote.kr', 'justinfo.co.kr', 'topnote.kr',
    'meganote.kr', 'smilenote.kr', 'healthcox.com', 'maxnote.kr',
    'must-joy.com', 'tripmarvel.com',
    'daynote.kr', 'nolplace.com', 'soulnote.kr', 'joynote.kr',
)
HOSTS = tuple(
    host
    for domain in CF_DOMAINS_16
    for host in (domain, f'www.{domain}')
)
AFFILIATE_HOSTS = (
    'toss.im',
    'link.coupang.com',
    'ohou.se',
    'oliveyoung.co.kr',
    'www.oliveyoung.co.kr',
    'adpick.co.kr',
    'www.adpick.co.kr',
)
ALL_OUTBOUND_HOSTS = HOSTS + AFFILIATE_HOSTS
SLOT_MODES_DEFAULT = {
    '08:00': 'warmup',
    '12:30': 'cf_inbound',
    '18:10': 'affiliate',
    '21:30': 'cf_inbound',
}


def stamp():
    return datetime.now(timezone.utc).isoformat()


def defaults():
    return {'schema':'threads-automation-v1','enabled':False,'account_key':'mustpickinfo',
            'accountConfirmed':True,'model':'gpt-6.1-sol','provider':'authenticated-codex-subscription',
            'trialDays':14,'continuousMode':False,'activatedAt':None,'endsAt':None,'startDate':None,'endDate':None,'timezone':'Asia/Seoul',
            'mainDailyCap':4,'mainTrialCap':56,'maxFollowups':1,'mainMaxChars':500,'followupMaxChars':500,
            'preferredTimes':['08:00','12:30','18:10','21:30'],'slotModes':dict(SLOT_MODES_DEFAULT),
            'followupDelaySeconds':{'min':90,'max':180,'default':120},
            'timesAreConfiguredPolicy':True,
            'api':{'base_url':'https://graph.threads.com/v1.0','token_env':'THREADS_ACCESS_TOKEN','token_file':None},
            'articleCatalog':[], 'accountTopic':'공식자료 기반 정책·생활정보·16개 CF 유입 및 제휴 수익화',
            'oauth':{'app_id_env':'THREADS_APP_ID','app_secret_env':'THREADS_APP_SECRET','redirect_uri':None},
            'connection':{'status':'unchecked','connected':False,'account_verified':False,'checked_at':None},
            'activationApproved':False}


def validate(config):
    if config.get('schema')!='threads-automation-v1' or config.get('provider')!='authenticated-codex-subscription':
        raise ValueError('Explicit Threads subscription configuration required')
    account=config.get('account_key')
    if account is not None and not re.fullmatch(r'[A-Za-z0-9_.-]{1,64}',account):
        raise ValueError('Non-secret account identifier required')
    if not isinstance(config.get('model'),str) or not config['model']:
        raise ValueError('Explicit subscribed model required; no provider fallback')
    trial_days = config.get('trialDays')
    daily_cap = config.get('mainDailyCap')
    if type(trial_days) is not int or trial_days < 14 or type(daily_cap) is not int or not (1 <= daily_cap <= 10) or config.get('maxFollowups') not in (0,1):
        raise ValueError('Approved configuration requires trialDays>=14, mainDailyCap in 1..10, and zero or one followup')
    if config.get('timezone')!='Asia/Seoul':raise ValueError('KST operation required')
    if config.get('mainMaxChars')!=500 or config.get('followupMaxChars')!=500:raise ValueError('Approved short text limits required')
    if any(not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d',time) for time in config.get('preferredTimes',[])):
        raise ValueError('Valid preferred times required')
    slot_modes = config.get('slotModes')
    if slot_modes is not None:
        if not isinstance(slot_modes, dict) or any(v not in ('warmup', 'cf_inbound', 'affiliate') for v in slot_modes.values()):
            raise ValueError('Invalid slotModes configuration')
    if config.get('enabled') and (not account or not config.get('activationApproved') or not config.get('activatedAt')):
        raise ValueError('Activation requires an explicitly confirmed account, approval and activation timestamp')
    return config


def load(path=CONFIG):
    if not Path(path).is_file():
        return defaults()
    raw = json.loads(Path(path).read_text(encoding='utf-8'))
    merged = {**defaults(), **raw}
    return validate(merged)


def save(config,path=CONFIG):
    validate(config);write(path,config)


def activate(config, *, approved=False, now=None):
    """Explicit future operation only; configuration/drafts never start trial dates."""
    if not approved:raise ValueError('Explicit activation approval required')
    if config.get('activatedAt'):raise ValueError('Trial already started; activation cannot reset the fourteen-day window')
    connection=config.get('connection',{})
    if not config.get('account_key') or connection.get('connected') is not True or connection.get('account_verified') is not True or connection.get('account_key')!=config['account_key']:
        raise ValueError('Verified connected account required before activation')
    if connection.get('publishReady') is not True:raise ValueError('Verified grants, expiry and quota readiness required before activation')
    now=now or datetime.now(timezone.utc)
    days=int(config.get('trialDays', 14))
    result=dict(config,enabled=True,activationApproved=True,activatedAt=now.isoformat(),endsAt=(now+timedelta(days=days)).isoformat(),
                startDate=now.astimezone(__import__('zoneinfo').ZoneInfo('Asia/Seoul')).date().isoformat(),
                endDate=(now+timedelta(days=days)-timedelta(microseconds=1)).astimezone(__import__('zoneinfo').ZoneInfo('Asia/Seoul')).date().isoformat())
    return validate(result)
