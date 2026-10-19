"""Bounded KnowledgeIn pilot. No scheduling or implicit model/provider fallback."""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from urllib.parse import parse_qs, urlsplit

from common.channel_attribution import build_attribution_receipt, validate_outbound_url, PRIORITY_CF_DOMAINS, is_dummy_rescue_url

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / 'server/data/kin.sqlite3'
PUBLIC = ROOT / 'dashboard/data/kin.json'
ACCOUNTS = ('adinfo0905', 'stone0747')
CF_BASE_DOMAINS = PRIORITY_CF_DOMAINS + (
    'baronote.kr',
    'justinfo.co.kr',
    'topnote.kr',
    'meganote.kr',
    'smilenote.kr',
    'healthcox.com',
    'maxnote.kr',
    'must-joy.com',
    'tripmarvel.com',
    'daynote.kr',
    'nolplace.com',
    'soulnote.kr',
    'joynote.kr',
)
HOSTS = (
    tuple(f'www.{d}' for d in CF_BASE_DOMAINS)
    + CF_BASE_DOMAINS
    + ('blog.naver.com', 'm.blog.naver.com')
)
TERMINAL_SEND = ('publishing', 'submitted_unverified', 'published_verified')
GLOBAL_DAILY_CAP = 20
ACCOUNT_DAILY_CAP = 10


def stamp():
    return datetime.now(timezone.utc).isoformat()


def today_kst():
    return datetime.now(__import__('zoneinfo').ZoneInfo('Asia/Seoul')).date().isoformat()


def enforce_trial_window(day):
    path=ROOT/'server/data/kin-automation.json'
    if path.is_file():
        config=json.loads(path.read_text(encoding='utf-8'))
        if not config.get('enabled'):
            raise ValueError('Automatic publication is disabled')
        if not config.get('continuousMode', False):
            if not config['startDate']<=day<=config['endDate']:
                raise ValueError('Outside the explicitly authorized seven-day publication window')


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':')).encode()).hexdigest()


def account_key(account):
    if account not in ACCOUNTS:
        raise ValueError('Only the two authorized non-real-name accounts are allowed')
    return account


def question_id(url):
    p = urlsplit(url)
    if (p.scheme != 'https' or p.netloc not in ('kin.naver.com', 'm.kin.naver.com')
            or p.username or p.password or p.fragment or p.path != '/qna/detail.naver'):
        raise ValueError('Exact HTTPS KnowledgeIn question URL required')
    ids = parse_qs(p.query).get('docId', [])
    if len(ids) != 1 or not re.fullmatch(r'[1-9][0-9]{4,14}', ids[0]):
        raise ValueError('Unambiguous numeric docId required')
    return ids[0]


def connect(path=DB):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=15)
    db.row_factory = sqlite3.Row
    db.execute('''CREATE TABLE IF NOT EXISTS questions (
      question_id TEXT PRIMARY KEY, account TEXT NOT NULL, state TEXT NOT NULL,
      document TEXT NOT NULL, evidence_hash TEXT NOT NULL, review_hash TEXT,
      answer_url TEXT, answer_id TEXT, result TEXT, created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL, send_day TEXT)''')
    db.execute('''CREATE TABLE IF NOT EXISTS discoveries (
      question_id TEXT PRIMARY KEY,account TEXT NOT NULL,document TEXT NOT NULL,created_at TEXT NOT NULL)''')
    db.execute('CREATE TABLE IF NOT EXISTS runtime(account TEXT PRIMARY KEY,reason TEXT,checked_at TEXT)')
    db.commit()
    return db


def article_snapshot(url, fallback_body=None):
    """Fetch clean owned article; reject redirects and hidden executable content."""
    from html.parser import HTMLParser
    import requests
    p = urlsplit(url)
    if (is_dummy_rescue_url(url) or p.scheme != 'https' or p.netloc not in HOSTS or p.query or p.fragment
            or not p.path or p.path == '/' or '\\' in url or any(ord(c) < 33 for c in url)):
        raise ValueError('Clean article on an approved owned host required')
    # Also apply the attribution library's stricter canonical validation.
    build_attribution_receipt(url, source='naver_kin', account=ACCOUNTS[0],
        work_date=today_kst(), publication_date=today_kst(), slot='00:00',
        article_id='validation', allowed_hosts=HOSTS)
    if isinstance(fallback_body, str) and len(fallback_body.strip()) >= 250:
        text = fallback_body.strip()[:45000]
        return {'url': url, 'body': text, 'body_sha256': hashlib.sha256(text.encode()).hexdigest(),
                'checked_at': stamp(), 'http_status': 200, 'scope': 'local_verified_publication'}
    response = requests.get(url, timeout=20, allow_redirects=False)
    response.raise_for_status()
    if response.status_code != 200 or 'text/html' not in response.headers.get('content-type', ''):
        raise ValueError('Article must return HTML 200 without redirect')
    if len(response.content) > 2_000_000:
        raise ValueError('Article response exceeds pilot limit')

    class Text(HTMLParser):
        def __init__(self):
            super().__init__(); self.skip = 0; self.parts = []
        def handle_starttag(self, tag, attrs):
            if tag in ('script', 'style', 'noscript'): self.skip += 1
        def handle_endtag(self, tag):
            if tag in ('script', 'style', 'noscript'): self.skip = max(0, self.skip-1)
        def handle_data(self, text):
            if not self.skip and text.strip(): self.parts.append(text.strip())
    article = (
        re.search(r'<article\b[^>]*>([\s\S]*?)</article\s*>', response.text, re.I)
        or re.search(r'<main\b[^>]*>([\s\S]*?)</main\s*>', response.text, re.I)
        or re.search(r'<div[^>]+class="[^"]*se-main-container[^"]*"[^>]*>([\s\S]*?)</div>', response.text, re.I)
    )
    if not article:
        raise ValueError('A distinct public article body is required')
    parser = Text(); parser.feed(article.group(1))
    text = '\n'.join(parser.parts)
    if len(text) < 250:
        raise ValueError('Insufficient public article body evidence')
    text = text[:45000]
    return {'url': url, 'body': text, 'body_sha256': hashlib.sha256(text.encode()).hexdigest(),
            'checked_at': stamp(), 'http_status': 200, 'scope':'article_element_text'}


def draft_binding(document):
    return digest({k: document[k] for k in ('account', 'question', 'article', 'answer_text', 'attribution')})


def record_discoveries(db, account, candidates):
    account_key(account)
    saved = []
    with db:
        for q in candidates:
            qid = question_id(q['question_url'])
            if not all(isinstance(q.get(key), str) and q[key].strip() for key in ('title','body','captured_at')):
                raise ValueError('Discovery requires captured question title/body/date')
            result = db.execute('INSERT OR IGNORE INTO discoveries VALUES (?,?,?,?)',
                                (qid,account,json.dumps(q,ensure_ascii=False),stamp()))
            if result.rowcount: saved.append(qid)
    return saved


def validate_document(document, reviewed=False):
    account_key(document['account'])
    q = document['question']; question_id(q['question_url'])
    if not all(isinstance(q.get(k), str) and q[k].strip() for k in ('title', 'body', 'captured_at')):
        raise ValueError('Question title/body/capture evidence required')
    article = document['article']
    receipt = document['attribution']
    validate_outbound_url(receipt['outboundUrl'], article['url'], source='naver_kin',
        account=document['account'], publication_date=receipt['publicationDate'],
        slot=receipt['scheduledSlot'], article_id=question_id(q['question_url']), allowed_hosts=HOSTS)
    if receipt['source'] != 'naver_kin' or receipt['account'] != document['account']:
        raise ValueError('Attribution identity mismatch')
    answer = document['answer_text']
    if not isinstance(answer, str) or not 180 <= len(answer) <= 4500:
        raise ValueError('A standalone substantive answer of 180–4500 characters is required')
    urls = re.findall(r'https?://[^\s<>"\']+', answer)
    if urls != [receipt['outboundUrl']]:
        raise ValueError('Exactly one approved attribution link required')
    if any(value in answer for value in ('제가 직접', '직접 사용해', '제가 방문', '전문가로서', '무조건', '100% 보장')):
        raise ValueError('Unsupported personal experience or certainty claim')
    if len(answer.replace(receipt['outboundUrl'], '').strip()) < 160:
        raise ValueError('Answer must be useful without following the link')
    if not article.get('body_sha256') or len(article.get('body', '')) < 250:
        raise ValueError('Public article snapshot required')
    if article['body_sha256'] != hashlib.sha256(article['body'].encode()).hexdigest():
        raise ValueError('Article snapshot hash mismatch')
    if reviewed and (document.get('review', {}).get('approved') is not True
                     or document['review'].get('binding') != draft_binding(document)
                     or not document['review'].get('reviewer')):
        raise ValueError('Independent supervisor review bound to this exact draft required')
    return question_id(q['question_url'])


def import_draft(db, document):
    qid = validate_document(document)
    now = stamp()
    # A global primary key prevents two accounts reserving the same question.
    with db:
        claimed = db.execute('SELECT account FROM discoveries WHERE question_id=?',(qid,)).fetchone()
        if claimed and claimed['account'] != document['account']:
            raise ValueError('Question already assigned to the other account')
        row = db.execute('SELECT * FROM questions WHERE question_id=?', (qid,)).fetchone()
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='automation_halts'").fetchone():
            if db.execute('SELECT 1 FROM automation_halts WHERE account=?',(document['account'],)).fetchone():
                raise ValueError('Account suspended after an explicit service protection/rejection; manual review required')
        if row:
            if row['account'] != document['account'] or row['state'] != 'drafted':
                raise ValueError('Question already reserved globally; no duplicate or uncertain retry')
            db.execute('UPDATE questions SET document=?,evidence_hash=?,review_hash=NULL,updated_at=? WHERE question_id=?',
                       (json.dumps(document, ensure_ascii=False),draft_binding(document),now,qid))
            return qid
        db.execute('INSERT INTO questions VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
            (qid, document['account'], 'drafted', json.dumps(document, ensure_ascii=False),
             draft_binding(document), None, None, None, None, now, now, None))
    return qid


def preflight_send(db, qid, account, run_id=None, cap=GLOBAL_DAILY_CAP):
    account_key(account);day=today_kst();enforce_trial_window(day)
    if db.execute("SELECT 1 FROM sqlite_master WHERE name='automation_halts'").fetchone():
        if db.execute('SELECT 1 FROM automation_halts WHERE account=?',(account,)).fetchone():
            raise ValueError('Account is suspended after explicit service protection')
    row=db.execute('SELECT * FROM questions WHERE question_id=?',(qid,)).fetchone()
    if not row or row['account']!=account or row['state']!='drafted':raise ValueError('Draft is not available')
    document=json.loads(row['document']);validate_document(document,reviewed=True)
    if document['attribution']['publicationDate']!=day:raise ValueError('Attribution date is stale')
    if db.execute("SELECT 1 FROM sqlite_master WHERE name='operating_cadence'").fetchone():
        cadence=db.execute('SELECT * FROM operating_cadence WHERE id=1').fetchone()
        linked=db.execute('SELECT question_id FROM automation_slots WHERE slot_id=?',(run_id,)).fetchone()
        if (not run_id or not cadence or cadence['active_run_id']!=run_id or cadence['active_account']!=account
                or not linked or linked['question_id']!=qid):
            raise ValueError('An exact active scheduler reservation is required')
        if cadence['last_completed_at'] and datetime.now(timezone.utc)<datetime.fromisoformat(cadence['last_completed_at'])+timedelta(minutes=15):
            raise ValueError('Minimum 15-minute global completion interval has not elapsed')
    if db.execute("SELECT COUNT(*) FROM questions WHERE send_day=? AND state='published_verified'",(day,)).fetchone()[0]>=cap:raise ValueError('Global daily submission cap')
    if db.execute("SELECT COUNT(*) FROM questions WHERE send_day=? AND account=? AND state='published_verified'",(day,account)).fetchone()[0]>=ACCOUNT_DAILY_CAP:raise ValueError('Account daily submission cap')
    return document


def begin_send(db, qid, account, cap=GLOBAL_DAILY_CAP, run_id=None):
    account_key(account)
    if not 1 <= cap <= GLOBAL_DAILY_CAP:
        raise ValueError('Global daily cap must be between 1 and ' + str(GLOBAL_DAILY_CAP))
    db.execute('BEGIN IMMEDIATE')
    try:
        day=today_kst()
        enforce_trial_window(day)
        preflight_send(db,qid,account,run_id,cap)
        row = db.execute('SELECT * FROM questions WHERE question_id=?', (qid,)).fetchone()
        if not row or row['account'] != account or row['state'] != 'drafted':
            raise ValueError('Question not available; uncertain sends must never be retried')
        document = json.loads(row['document']); validate_document(document, reviewed=True)
        if document['attribution']['publicationDate'] != day:
            raise ValueError('Attribution date is stale; prepare and review for today')
        count = db.execute("SELECT COUNT(*) FROM questions WHERE send_day=? AND state='published_verified'", (day,)).fetchone()[0]
        if count >= cap:
            raise ValueError('Global pilot daily send cap reached')
        account_count = db.execute("SELECT COUNT(*) FROM questions WHERE send_day=? AND account=? AND state='published_verified'",
                                   (day,account)).fetchone()[0]
        if account_count >= ACCOUNT_DAILY_CAP:
            raise ValueError('Account daily send cap reached (' + str(ACCOUNT_DAILY_CAP) + ')')
        db.execute("UPDATE questions SET state='publishing',review_hash=?,send_day=?,updated_at=? WHERE question_id=?",
                   (draft_binding(document), day, stamp(), qid))
        db.commit()
        return document
    except Exception:
        db.rollback(); raise


def finish_send(db, qid, result):
    answer_id = result.get('answer_id')
    answer_id = str(answer_id) if answer_id is not None else None
    with db:
        db.execute("UPDATE questions SET state='submitted_unverified',answer_url=?,answer_id=?,result=?,updated_at=? WHERE question_id=? AND state='publishing'",
                   (result.get('answer_url'), answer_id, json.dumps(result, ensure_ascii=False), stamp(), qid))


def record_verification(db, qid, evidence):
    row = db.execute('SELECT * FROM questions WHERE question_id=?', (qid,)).fetchone()
    if not row or row['state'] not in TERMINAL_SEND:
        raise ValueError('No send attempt to verify')
    document = json.loads(row['document'])
    identity = (evidence.get('account') == document['account'] and evidence.get('question_id') == qid and row['answer_id']
                and str(evidence.get('answer_id')) == row['answer_id'])
    verified = (evidence.get('verified') is True and evidence.get('public') is True and identity
                and evidence.get('answer_text_sha256') == hashlib.sha256(document['answer_text'].encode()).hexdigest()
                and evidence.get('outbound_url') == document['attribution']['outboundUrl'])
    if verified:
        with db:
            db.execute("UPDATE questions SET state='published_verified',result=?,updated_at=? WHERE question_id=?",
                       (json.dumps(evidence, ensure_ascii=False), stamp(), qid))
        from common.llm_client import memory_event
        memory_event(f'kin:{qid}:{row["answer_id"]}', 'pipeline_publication_verified',
                     'KnowledgeIn public answer identity, content hash and outbound URL verified.',
                     evidence=evidence, session_id=f'kin:{qid}')
    return bool(verified)


def snapshot(db, output=PUBLIC):
    counts = dict(db.execute('SELECT state,COUNT(*) FROM questions GROUP BY state').fetchall())
    rows = [dict(r) for r in db.execute('SELECT account,state,answer_url,updated_at,send_day,document FROM questions ORDER BY updated_at DESC LIMIT 30')]
    track_counts = {'track_a_latest': 0, 'track_b_search_top': 0}
    for row in rows:
        doc = json.loads(row.pop('document'))
        q = doc['question']
        art_url = doc.get('article', {}).get('url', '')
        dom = urlsplit(art_url).hostname or ''
        tr = doc.get('track') or q.get('track') or ('track_a_latest' if q.get('search_sort') == 'date' else 'track_b_search_top')
        track_counts[tr] = track_counts.get(tr, 0) + 1
        row.update(
            title=q['title'],
            question_url=q['question_url'],
            track=tr,
            target_domain=dom.removeprefix('www.'),
        )
    pending = db.execute('SELECT * FROM discoveries WHERE question_id NOT IN (SELECT question_id FROM questions)').fetchall()
    counts['discovered'] = len(pending)
    for item in pending[:30]:
        q = json.loads(item['document'])
        tr = q.get('track') or ('track_a_latest' if q.get('search_sort') == 'date' else 'track_b_search_top')
        rows.append({'account':item['account'],'state':'discovered','answer_url':None,
                     'updated_at':item['created_at'],'title':q['title'],'question_url':q['question_url'],
                     'track':tr,'target_domain':''})
    rows = sorted(rows,key=lambda r:r['updated_at'],reverse=True)[:30]
    for row in rows:
        url = row['answer_url']
        if url:
            try:
                parts = urlsplit(url)
                question_id(url.split('#', 1)[0])
                if parts.fragment and not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', parts.fragment):
                    raise ValueError('Invalid answer fragment')
            except ValueError:
                row['answer_url'] = None
    reasons = {r['account']:r['reason'] for r in db.execute('SELECT * FROM runtime') if r['reason']}
    by_account = {account:{state:n for state,n in db.execute('SELECT state,COUNT(*) FROM questions WHERE account=? GROUP BY state',(account,))} for account in ACCOUNTS}
    for account in ACCOUNTS:
        by_account[account]['discovered'] = sum(r['account']==account for r in pending)
    daily_rows=db.execute("SELECT account,state FROM questions WHERE send_day=? AND state != 'skipped'",(today_kst(),)).fetchall()
    published_today = sum(r['state']=='published_verified' for r in daily_rows)
    attempted_today = len(daily_rows)
    daily={'date':today_kst(),'attempted':attempted_today,
           'publishedVerified':published_today,
           'remainingScheduled':max(0, GLOBAL_DAILY_CAP - published_today),
           'retryAttemptsToday':max(0, attempted_today - published_today),
           'globalCap':GLOBAL_DAILY_CAP,'accountCap':ACCOUNT_DAILY_CAP,
           'byAccount':{account:{'attempted':sum(r['account']==account for r in daily_rows),
                                'publishedVerified':sum(r['account']==account and r['state']=='published_verified' for r in daily_rows),
                                'remainingScheduled':max(0, ACCOUNT_DAILY_CAP - sum(r['account']==account and r['state']=='published_verified' for r in daily_rows))} for account in ACCOUNTS}}
    value = {'schema': 'naver-kin-pilot-v1', 'checkedAt': stamp(), 'accounts': list(ACCOUNTS),
             'counts': counts, 'recent': rows, 'trackCounts': track_counts,
             'inboundSessions': None, 'attributedRevenue': None,
             'measurementStatus': 'unmeasured', 'complete': False,
             'blockedReason': '; '.join(account+': '+reason for account,reason in reasons.items()) or None,
             'byAccount':by_account,'accountBlockedReasons':reasons,'daily':daily}
    for key,filename in [('measurement','kin-measurement.json'),('schedule','kin-automation-state.json'),('retention','kin-retention.json')]:
        try:value[key]=json.loads((ROOT/'server/data'/filename).read_text(encoding='utf-8'))
        except (OSError,ValueError):pass
    try:
        config=json.loads((ROOT/'server/data/kin-automation.json').read_text(encoding='utf-8'))
        value['automation']={key:config.get(key) for key in ('enabled','startDate','endDate','measurementEndDate','mode','intervalMinutes','intervalJitterMinutes','continuousMode','pollMinutes','globalDailyCap','accountDailyCap','model','provider')}
        value['automation']['scheduleDescription']='작업 종료 후 18~22분 지터(평균 20분) 계정 교대 · 개별 계정 40~45분 안전 텀 · 하루 20건(계정당 10건)'
        value['automation']['lastRun']=value.get('schedule')
        value['automation']['lastRunAt']=value.get('schedule',{}).get('lastRunAt')
        for key in ('nextEligibleAt','nextAccount','activeRunId','activeAccount','activeStartedAt','cadenceState','globalRemainingRuns','byAccountRemainingRuns','operationCounts','submissionCounts','retryAttemptsToday'):
            value['automation'][key]=value.get('schedule',{}).get(key)
        # Always enforce remaining = 20 - publishedVerified so failed/interrupted runs never deduct daily quota
        value['automation']['globalRemainingRuns'] = max(0, int(config.get('globalDailyCap', GLOBAL_DAILY_CAP)) - published_today)
        value['automation']['byAccountRemainingRuns'] = {
            acc: max(0, int(config.get('accountDailyCap', ACCOUNT_DAILY_CAP)) - daily['byAccount'][acc]['publishedVerified'])
            for acc in ACCOUNTS
        }
        value['automation']['retryAttemptsToday'] = daily['retryAttemptsToday']
        value['automation']['checkedAt']=value.get('schedule',{}).get('checkedAt')
        value['automation']['state']=value.get('schedule',{}).get('state','not_run')
        if db.execute("SELECT 1 FROM sqlite_master WHERE name='automation_slots'").fetchone():
            last=db.execute('''SELECT a.account,a.state,a.reason,a.updated_at,a.question_id,
              q.state question_state,q.send_day FROM automation_slots a LEFT JOIN questions q
              ON q.question_id=a.question_id ORDER BY a.planned_at DESC LIMIT 1''').fetchone()
            if last:
                value['automation']['lastOperation']={'account':last['account'],'state':last['state'],
                    'reason':last['reason'],'updatedAt':last['updated_at'],'questionId':last['question_id'],
                    'questionState':last['question_state'],'submissionAttempted':last['send_day'] is not None,
                    'submitted':False if last['question_state'] in (None,'drafted') else True if last['question_state']=='published_verified' else None}
    except (OSError,ValueError):pass
    from common.dashboard_jobs import write
    write(output,value)
    return value


@contextmanager
def account_lock(account):
    account_key(account)
    directory = ROOT / 'server/data'; directory.mkdir(parents=True, exist_ok=True)
    f = (directory / ('kin-' + account + '.lock')).open('a+b')
    try:
        f.seek(0, 2)
        if not f.tell(): f.write(b'0'); f.flush()
        f.seek(0)
        if __import__('os').name == 'nt':
            import msvcrt; msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl; fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        f.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--account', choices=ACCOUNTS)
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument('--status', action='store_true')
    actions.add_argument('--discover', action='store_true')
    actions.add_argument('--prepare', action='store_true')
    actions.add_argument('--import-draft', type=Path)
    actions.add_argument('--run-once', action='store_true')
    actions.add_argument('--verify', metavar='QUESTION_ID')
    parser.add_argument('--keyword', action='append', default=[])
    parser.add_argument('--question-json', type=Path)
    parser.add_argument('--article-url')
    parser.add_argument('--answer-file', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--daily-cap', type=int, default=GLOBAL_DAILY_CAP)
    parser.add_argument('--question-id', help='Select one exact drafted question for --run-once')
    parser.add_argument('--run-id',help='Internal operating reservation; never bypasses daily or date gates')
    args = parser.parse_args(argv)
    db = connect()
    try:
        if args.status: print(json.dumps(snapshot(db), ensure_ascii=False, indent=2)); return
        if not args.account: parser.error('--account is required')
        with db:
            db.execute('INSERT OR REPLACE INTO runtime VALUES (?,?,?)',(args.account,None,stamp()))
        if args.import_draft:
            document = json.loads(args.import_draft.read_text(encoding='utf-8'))
            if document['account'] != args.account: raise ValueError('Draft account mismatch')
            print(import_draft(db, document)); return
        if args.prepare:
            if not all((args.question_json, args.article_url, args.answer_file, args.output)):
                parser.error('--prepare needs --question-json --article-url --answer-file --output')
            q = json.loads(args.question_json.read_text(encoding='utf-8'))
            qid = question_id(q['question_url'])
            now = datetime.now(__import__('zoneinfo').ZoneInfo('Asia/Seoul'))
            receipt = build_attribution_receipt(args.article_url, source='naver_kin', account=args.account,
                work_date=now.date().isoformat(), publication_date=now.date().isoformat(),
                slot=now.strftime('%H:%M'), article_id=qid, allowed_hosts=HOSTS)
            answer = args.answer_file.read_text(encoding='utf-8').replace('{OUTBOUND_URL}', receipt['outboundUrl'])
            document = {'account':args.account,'question':q,'article':article_snapshot(args.article_url),
                        'answer_text':answer,'attribution':receipt}
            validate_document(document)
            document['review'] = {'approved':False,'binding':draft_binding(document),'reviewer':''}
            output = args.output.resolve()
            if output.is_relative_to((ROOT/'dashboard').resolve()):
                raise ValueError('Private draft must not be saved under the public dashboard')
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(document,ensure_ascii=False,indent=2),encoding='utf-8')
            print(str(output)); return
        from naver_kin import browser
        with account_lock(args.account):
            if args.discover:
                candidates = browser.discover(args.account, args.keyword, limit=10)
                record_discoveries(db,args.account,candidates)
                print(json.dumps(candidates, ensure_ascii=False, indent=2)); return
            if args.verify:
                row = db.execute('SELECT * FROM questions WHERE question_id=? AND account=?', (args.verify,args.account)).fetchone()
                if not row: raise ValueError('Unknown account/question')
                doc = json.loads(row['document'])
                evidence = browser.verify_public(args.account,row['answer_url'],doc['answer_text'],doc['attribution']['outboundUrl'],row['answer_id'])
                print(record_verification(db,args.verify,evidence)); return
            query = "SELECT question_id,document FROM questions WHERE account=? AND state='drafted'"
            parameters = [args.account]
            if args.question_id:
                query += ' AND question_id=?'; parameters.append(args.question_id)
            row = db.execute(query+' ORDER BY created_at LIMIT 1', parameters).fetchone()
            if not row: raise ValueError('No independently reviewed imported draft; discover and review first')
            doc = json.loads(row['document'])
            preflight_send(db,row['question_id'],args.account,args.run_id,args.daily_cap)
            current_question = browser.read_question(args.account,doc['question']['question_url'])
            normalized = lambda text: ' '.join(text.split())
            if any(normalized(current_question.get(key,'')) != normalized(doc['question'][key]) for key in ('title','body')):
                raise ValueError('Question changed since review; capture and review again')
            fresh = article_snapshot(
                doc['article']['url'],
                fallback_body=doc['article'].get('body') if doc['article'].get('scope') == 'local_verified_publication' else None,
            )
            if fresh['body_sha256'] != doc['article']['body_sha256']:
                raise ValueError('Article changed since review; review again')
            validate_document(doc, reviewed=True)
            started = False
            def before_submit():
                nonlocal started
                if started: raise ValueError('Duplicate submit callback')
                begin_send(db,row['question_id'],args.account,args.daily_cap,run_id=args.run_id)
                started = True
            try:
                result = browser.publish(args.account,doc['question']['question_url'],doc['answer_text'],before_submit=before_submit)
            except Exception as exc:
                if started:
                    finish_send(db,row['question_id'],{'reason':'Publication uncertain: '+type(exc).__name__})
                raise
            if not started:
                raise ValueError('Adapter did not submit; draft remains pending')
            finish_send(db,row['question_id'],result)
            print(json.dumps(result,ensure_ascii=False))
    except Exception as exc:
        if args.account:
            # Never expose arbitrary adapter/page text or credentials in public status.
            with db:
                db.execute('INSERT OR REPLACE INTO runtime VALUES (?,?,?)',
                           (args.account,'Operation blocked ('+type(exc).__name__+'); inspect private worker output',stamp()))
        raise
    finally:
        snapshot(db); db.close()


if __name__ == '__main__':
    main()
