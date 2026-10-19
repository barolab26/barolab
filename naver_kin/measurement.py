"""Read-only KnowledgeIn UTM measurement; reuses the existing GA4 reader.

No synthetic visits, tracking tags or credential copies. Run python -m
naver_kin.measurement. Scheduler calls collect() once after its publication cycle.
"""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
import sys
from zoneinfo import ZoneInfo
from urllib.parse import urlsplit

from common.dashboard_jobs import write
from .pipeline import ROOT, DB, ACCOUNTS
from .experiment import BASELINE_START, BASELINE_END, TRIAL_START, TRIAL_END, FINAL_COLLECTION

from common.channel_attribution import PRIORITY_CF_DOMAINS
HOSTS = tuple('www.' + domain for domain in PRIORITY_CF_DOMAINS)

PRIVATE = ROOT / 'server/data/kin-measurement.json'
PUBLIC = ROOT / 'dashboard/data/kin-measurement.json'
BASELINE = ROOT / 'server/data/kin-measurement-baseline.json'
METRICS = ['sessions', 'engagedSessions', 'screenPageViews']
DIMENSIONS = ['date', 'sessionManualAdContent']


class MetadataClient:
    """Keep safe API completeness evidence while reusing existing report parser."""
    def __init__(self, client):
        self.client = client
        self.metadata = {}

    def request(self, *args, **kwargs):
        response = self.client.request(*args, **kwargs)
        if response.ok:
            raw = response.json(); meta = raw.get('metadata', {})
            self.metadata = {key: meta.get(key) for key in ('timeZone', 'currencyCode', 'subjectToThresholding', 'samplingMetadatas', 'dataLossFromOtherRow')}
            self.metadata.update(rowCount=raw.get('rowCount', 0), returnedRows=len(raw.get('rows', [])))
        return response


def report_body(start, end, hosts):
    filters = [{'filter': {'fieldName': name, 'stringFilter': {'matchType': 'EXACT', 'value': value, 'caseSensitive': True}}}
               for name, value in [('sessionSource', 'naver_kin'), ('sessionMedium', 'referral'), ('sessionManualCampaignName', 'cf_bridge')]]
    filters.append({'filter': {'fieldName': 'hostName', 'inListFilter': {'values': hosts, 'caseSensitive': False}}})
    return {'dateRanges': [{'startDate': start, 'endDate': end}],
            'dimensions': [{'name': name} for name in DIMENSIONS],
            'metrics': [{'name': name} for name in METRICS],
            'dimensionFilter': {'andGroup': {'expressions': filters}}, 'limit': 10000}


def ledger(db):
    mapping = {}
    for row in db.execute('SELECT question_id,account,state,document,answer_url,send_day FROM questions'):
        if row['account'] not in ACCOUNTS:
            continue
        doc = json.loads(row['document']); attribution = doc.get('attribution', {})
        token = attribution.get('utmContent')
        if isinstance(token, str) and re.fullmatch(r'[A-Za-z0-9_-]{1,200}', token):
            mapping[token] = {'account': row['account'], 'questionId': row['question_id'],
                              'state': row['state'], 'answerUrl': row['answer_url'],
                              'canonicalUrl': attribution.get('canonicalUrl'), 'sendDay': row['send_day']}
    return mapping


def daily_funnel(db, start, end):
    """Current-state cohort counts, not historical transition/event counts."""
    days = {str(start + timedelta(days=i)): {'day': str(start + timedelta(days=i)), 'discovered': 0, 'drafted': 0, 'attempted': 0, 'published_verified': 0} for i in range((end-start).days+1)}
    def date(value):
        try:
            parsed = datetime.fromisoformat(value)
            if parsed.tzinfo is None: return None
            return str(parsed.astimezone(ZoneInfo('Asia/Seoul')).date())
        except (ValueError, TypeError): return None
    for row in db.execute('SELECT account,created_at FROM discoveries'):
        key = date(row['created_at'])
        if row['account'] in ACCOUNTS and key in days: days[key]['discovered'] += 1
    for row in db.execute('SELECT account,state,created_at,send_day FROM questions'):
        if row['account'] not in ACCOUNTS: continue
        key = date(row['created_at'])
        if key in days: days[key]['drafted'] += 1
        if row['send_day'] in days:
            days[row['send_day']]['attempted'] += 1
            if row['state'] == 'published_verified': days[row['send_day']]['published_verified'] += 1
    return list(reversed(list(days.values())))


def collect(db=None, now=None, *, config=None, persist=True):
    """Return fixed baseline or approved trial through yesterday (Asia/Seoul).

    Values are null for unconnected/error/limited sites. Empty successful API
    reports mean observed zero, still provisional because GA4 reporting can lag.
    Baseline is an immutable first collection, not a pre/post causal comparison.
    """
    sys.path.insert(0, str(ROOT / 'dashboard')) if str(ROOT / 'dashboard') not in sys.path else None
    import traffic
    from metrics import read_json, CONFIG
    from .pipeline import connect
    now = now or datetime.now(timezone.utc)
    day = now.astimezone(ZoneInfo('Asia/Seoul')).date()
    period_kind = 'baseline' if day <= TRIAL_START else 'trial_to_yesterday'
    if period_kind == 'baseline':
        start, end = BASELINE_START, BASELINE_END
    else:
        start, end = TRIAL_START, min(day - timedelta(days=1), TRIAL_END)
    config = read_json(CONFIG) if config is None else config
    owned_db = db is None
    db = connect(DB) if owned_db else db
    try:
        mapping = ledger(db)
        funnel_start, funnel_end = (TRIAL_START, min(day, TRIAL_END)) if day >= TRIAL_START else (day, day)
        funnel = daily_funnel(db, funnel_start, funnel_end)
    finally:
        if owned_db: db.close()
    result = {'schema': 'naver-kin-measurement-v1', 'checkedAt': now.isoformat(),
              'source': 'GA4 Data API', 'timezone': 'Asia/Seoul', 'startDate': str(start), 'endDate': str(end),
              'trialStartDate': str(TRIAL_START), 'trialEndDate': str(TRIAL_END), 'finalCollectionDate': str(FINAL_COLLECTION),
              'baselineStartDate': str(BASELINE_START), 'baselineEndDate': str(BASELINE_END),
              'periodKind': period_kind, 'trialCollectionPending': period_kind == 'baseline',
              'trackingValidationStatus': 'unverified_stream_binding',
              'trackingValidationNote': '기사 HTML의 GA4 태그와 UTM 쿼리 보존은 별도 확인. GA Admin dataStreams 접근 403으로 조회 속성과 태그 ID 일치 미검증. 빈 GA4 응답은 추적 정상 증거가 아닙니다.',
              'scope': 'owned approved hosts; exact sessionSource=naver_kin, sessionMedium=referral, sessionManualCampaignName=cf_bridge',
              'provisional': True, 'lagNote': '최근 48시간은 GA4 처리 지연으로 변할 수 있습니다. 미측정·동의 거부·차단 방문은 포함되지 않습니다.',
              'causalityNote': 'UTM 세션 귀속이며 실제 사람·증분 효과·수익 발생을 단독 증명하지 않습니다.',
              'sites': [], 'sessions': None, 'engagedSessions': None, 'pageViews': None,
              'publisherRevenue': None, 'revenueStatus': 'unverified_publisher_link',
              'revenueReason': 'GA4 게시자 광고 수익 연결과 답변별 수익 범위를 검증하지 못했습니다. AdSense 전체 수익을 배분하지 않습니다.',
              'rows': [], 'dailyFunnel': funnel, 'funnelStartDate': str(funnel_start), 'funnelEndDate': str(funnel_end),
              'funnelTodayProvisional': funnel_end == day,
              'funnelPeriodKind': 'trial' if day >= TRIAL_START else 'pretrial_check',
              'funnelScope': '발굴·초안은 생성일, 제출·공개검증은 제출일 코호트의 현재 상태; 오늘은 미실행 슬롯 포함 잠정 집계; 전이 이벤트 수 아님',
              'complete': False, 'status': 'not_collected'}
    validation_path = ROOT / 'server/data/kin-tracking-validation.json'
    if validation_path.exists():
        validation = read_json(validation_path)
        result['trackingValidation'] = validation
        result['trackingValidationNote'] = 'GA4 조회 성공 · 두 사이트 기존 호스트 방문 확인 · 기사 UTM 도착 쿼리 보존 확인. GA 태그 ID와 조회 속성의 직접 일치는 Admin 권한 부족으로 미검증입니다. 조회 성공만으로 지식iN 유입 성과를 판정하지 않습니다.'
    for host in HOSTS:
        domain = host.removeprefix('www.'); settings = config.get('sites', {}).get(domain, {})
        site = {'host': host, 'status': 'not_connected', 'sessions': None, 'engagedSessions': None, 'pageViews': None}
        result['sites'].append(site)
        if not settings.get('ga4_property') or not settings.get('analytics_reader'):
            site['reason'] = 'GA4 속성 또는 조회 계정 미연결'; continue
        try:
            with traffic.session(settings, config.get('analytics_readers', {}), 'https://www.googleapis.com/auth/analytics.readonly') as client:
                observed = MetadataClient(client)
                rows, limited = traffic.ga_report(observed, settings['ga4_property'], report_body(str(start), str(end), [domain, host]), DIMENSIONS)
            site['reportMetadata'] = observed.metadata
            if limited:
                site.update(status='limited', reason='GA4 임계값·샘플링·기타행 제한으로 합계 미확정'); continue
            totals = [0, 0, 0]; safe_rows = []
            for keys, values in rows:
                date, token = keys
                actual_host = host
                date = datetime.strptime(date, '%Y%m%d').date()
                if not start <= date <= end or actual_host.lower() not in (domain, host) or len(values) != 3:
                    raise ValueError('GA4 scope mismatch')
                totals = [a+b for a,b in zip(totals, values)]
                match = mapping.get(token)
                if match and urlsplit(match.get('canonicalUrl') or '').hostname not in (domain, host):
                    match = None
                safe_rows.append({'day': str(date), 'host': actual_host, 'utmContent': token,
                    'sessions': values[0], 'engagedSessions': values[1], 'pageViews': values[2],
                    'mappingStatus': 'ledger_matched' if match else 'unattributed',
                    **(match or {})})
            site.update(status='collected', sessions=totals[0], engagedSessions=totals[1], pageViews=totals[2])
            result['rows'].extend(safe_rows)
        except Exception as exc:
            site.update(status='collection_error', reason='GA4 조회 실패: ' + type(exc).__name__)
    collected = [site for site in result['sites'] if site['status'] == 'collected']
    result['complete'] = len(collected) == len(HOSTS)
    result['status'] = 'collected' if result['complete'] else ('partial' if collected else 'not_collected')
    if result['complete']:
        for key in ('sessions', 'engagedSessions', 'pageViews'):
            result[key] = sum(site[key] for site in collected)
    result['matchedSessions'] = sum(row['sessions'] for row in result['rows'] if row['mappingStatus'] == 'ledger_matched') if result['complete'] else None
    result['unmatchedSessions'] = sum(row['sessions'] for row in result['rows'] if row['mappingStatus'] == 'unattributed') if result['complete'] else None
    if persist:
        write(PRIVATE, result); write(PUBLIC, result)
        if period_kind == 'baseline' and result['complete'] and not BASELINE.exists(): write(BASELINE, result)
    return result


if __name__ == '__main__':
    value = collect()
    print(json.dumps({key: value[key] for key in ('status', 'startDate', 'endDate', 'sessions', 'engagedSessions', 'pageViews', 'complete', 'sites')}, ensure_ascii=False, indent=2))
