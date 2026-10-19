"""Join existing public URLs with separate index and search evidence; no publishing."""
import math
from datetime import datetime, timedelta, timezone
from urllib.parse import unquote, urlsplit


def fresh(value, now, hours):
    try:
        age = now - datetime.fromisoformat(value)
        return timedelta(0) <= age <= timedelta(hours=hours)
    except (ValueError, TypeError):
        return False


def url_key(url, domain, host_alias=False):
    try:
        if isinstance(url, str):
            parts = url.split()
            if not parts:
                return None
            url = parts[0]
        value = urlsplit(url)
        if value.scheme != 'https' or value.hostname not in {domain, 'www.' + domain} or value.port:
            return None
        host = domain if host_alias else value.hostname
        return host, unquote(value.path), value.query
    except (ValueError, TypeError):
        return None


def next_action(index, performance, evidence):
    coverage = (evidence.get('coverageState') or '').lower()
    if index == 'not_indexed':
        if any(word in coverage for word in ('canonical', 'duplicate', 'alternate', 'redirect', '대표', '중복', '대체', '리디렉션')):
            return '대표 URL 확인', '정상적인 중복·리디렉션 제외인지 확인하고, 대표 글의 색인 상태를 검사합니다.'
        if any(word in coverage for word in ('noindex', 'robots', '404', '5xx', 'server', '차단', '서버')):
            return '접근·색인 설정 점검', 'HTTP 응답, robots.txt, noindex, 렌더링과 대표 URL 설정을 확인합니다.'
        if 'crawled' in coverage or '크롤링됨' in coverage:
            return '내용·중복 점검', '이미 수집된 글입니다. 독창성·검색 의도·중복 여부를 검토하고 실질적으로 보강합니다.'
        return 'URL 검사로 원인 확인', '미색인 사유와 마지막 수집 시각을 확인한 뒤, 접근·내부 링크·사이트맵·본문을 점검합니다.'
    if performance == 'deep':
        return '검색 의도·차별점 재검토', '노출된 검색어와 상위 글을 비교해 주제 적합성, 직접 확인한 정보, 최신성·내부 링크를 보강합니다.'
    if performance == 'opportunity':
        return '상승 후보 보강', '노출이 있는 글부터 빠진 답변·비교·사례를 보완하고 다음 보고서에서 클릭·노출 변화를 확인합니다.'
    if performance == 'top':
        return '상위 글 유지·클릭 점검', '정확성과 최신성을 유지하고, 검색어와 제목·설명의 일치 여부 및 클릭률을 점검합니다.'
    if index == 'indexed':
        return '검색 수요·실적 범위 확인', '색인은 확인됐습니다. 글별 실적 보고서와 검색 수요를 확인하며, 보고서에 행이 없다고 미노출로 단정하지 않습니다.'
    return '개별 색인 검사 필요', '미색인으로 분류하지 않습니다. 개별 URL 검사와 페이지별 검색 실적 수집이 먼저 필요합니다.'


def summary(records, analysis, now=None):
    now = now or datetime.now(timezone.utc)
    traffic = {r['site']['site_id']: r for r in analysis.get('sites', [])}
    rows, source_domains, inventory_domains = [], [], []
    counts = {key: 0 for key in ('not_indexed', 'deep', 'opportunity', 'top', 'indexed_no_report', 'unknown')}
    for record in records:
        site = record.get('site', {})
        if site.get('platform') != 'cf':
            continue
        domain, posts = site['site_id'], record.get('posts', {})
        inventory_current = fresh(posts.get('checkedAt'), now, 26)
        if inventory_current and posts.get('complete'):
            inventory_domains.append(domain)
        inspections = {url_key(r.get('url'), domain): r for r in record.get('google', {}).get('urls', [])}
        source = traffic.get(domain, {}).get('google', {})
        report = source.get('periods', {}).get('month', {})
        page_current = (source.get('status') in ('collected', 'partial') and not source.get('stale')
                        and fresh(source.get('checkedAt'), now, 2) and report.get('pagesStatus') == 'collected')
        page_rows = {}
        if page_current:
            source_domains.append(domain)
            for row in report.get('pages', []):
                key = url_key(row.get('page'), domain, host_alias=True)
                if key:
                    page_rows.setdefault(key, []).append(row)
        seen = set()
        for url in posts.get('urls', []):
            key = url_key(url, domain)
            if key is None or key in seen:
                continue
            seen.add(key)
            evidence = inspections.get(key, {})
            index = 'unknown'
            if fresh(evidence.get('checkedAt'), now, 26):
                index = 'indexed' if evidence.get('indexed') is True else 'not_indexed' if evidence.get('indexed') is False else 'unknown'
            success_at = evidence.get('checkedAt') if isinstance(evidence.get('indexed'), bool) else evidence.get('lastSuccessAt') if isinstance(evidence.get('lastIndexed'), bool) else None
            success_stale = bool(success_at) and not fresh(success_at, now, 26)
            pending_reason = ('이전 색인 판정 만료' if success_stale else
                              '검사 오류 · 재시도 필요' if evidence.get('attemptStatus') == 'failed' or (evidence and not success_at and evidence.get('reason')) else
                              '검사 결과 미확정' if evidence else '개별 검사 이력 없음')
            candidates = page_rows.get(url_key(url, domain, host_alias=True), [])
            # Several canonical host rows cannot be collapsed into an invented page average.
            page = candidates[0] if len(candidates) == 1 else None
            position = page.get('position') if page else None
            valid_position = isinstance(position, (int, float)) and math.isfinite(position) and position > 0
            performance = ('deep' if position > 100 else 'opportunity' if position > 10 else 'top') if valid_position and page.get('impressions', 0) > 0 else 'unknown'
            bucket = 'not_indexed' if index == 'not_indexed' else performance if performance != 'unknown' else 'indexed_no_report' if index == 'indexed' else 'unknown'
            counts[bucket] += 1
            action, explanation = next_action(index, performance, evidence)
            rows.append({'domain': domain, 'url': url, 'index': index, 'inspectionAt': evidence.get('checkedAt'),
                         'inspectionStale': success_stale,
                         'inspectionPendingReason': pending_reason,
                         'inspectionAttemptAt': evidence.get('attemptAt'),
                         'coverageState': evidence.get('coverageState'), 'googleCanonical': evidence.get('googleCanonical'),
                         'requestOutcome': evidence.get('outcome'), 'performance': performance, 'bucket': bucket,
                         'inventoryStale': not inventory_current, 'search': page,
                         'searchStart': report.get('start') if page_current else None,
                         'searchEnd': report.get('end') if page_current else None,
                         'pageReportAvailable': page_current, 'ambiguousPage': len(candidates) > 1,
                         'action': action, 'explanation': explanation})
    pending = [r for r in rows if r['index'] == 'unknown']
    return {'rows': rows, 'counts': counts, 'inventoryTotal': len(rows), 'inventoryDomains': len(inventory_domains),
            'inspectionPending': len(pending),
            'inspectionPendingReasons': {reason: sum(r['inspectionPendingReason'] == reason for r in pending) for reason in ('이전 색인 판정 만료', '검사 오류 · 재시도 필요', '검사 결과 미확정', '개별 검사 이력 없음')},
            'expectedDomains': analysis.get('expectedDomains', 16), 'pageReportDomains': len(source_domains),
            'checkedAt': now.isoformat(), 'scope': 'Google · CF 공개 글 목록 · 최근 30일 페이지 실적',
            'note': '검색 실적과 현재 색인 검사는 별개입니다. 보고서 행 없음은 미색인·노출 0을 뜻하지 않습니다.'}
