"""Parse actual Naver reservation list observations."""
from datetime import datetime, timedelta
TTL = timedelta(minutes=10)

def _fresh(value, now, lifetime=TTL):
    observed = datetime.fromisoformat(value)
    return observed.tzinfo is not None and timedelta(0) <= now - observed <= lifetime

def validated_reservation_rows(reservation, blog, now):
    """Validate the existing collector's two complete modern-editor observations."""
    try:
        count, entries = reservation['reservationCount'], reservation['reservations']
        if (not _fresh(reservation['checkedAt'], now)
                or reservation.get('verificationSource') != 'playwright-reservation-list'
                or reservation.get('reservationListComplete') is not True
                or type(count) is not int or count < 0 or not isinstance(entries, list)
                or len(entries) != count or reservation.get('independentReadings') != 2):
            return None
        seen = set()
        for entry in entries:
            title, when = entry['title'], entry['reserveTime']
            if not isinstance(title, str) or not title.strip() or not isinstance(when, str):
                return None
            parsed = datetime.strptime(when, '%Y-%m-%d %H:%M')
            if parsed.strftime('%Y-%m-%d %H:%M') != when or (title, when) in seen:
                return None
            seen.add((title, when))
        counts = reservation['serverCountEvidence']
        if not isinstance(counts, list) or len(counts) != 4:
            return None
        for pass_no in (1, 2):
            for version in ('2', '4'):
                rows = [r for r in counts if r.get('pass') == pass_no
                        and r.get('requestQuery') == {'blogId': [blog], 'editorVersion': [version]}]
                if len(rows) != 1 or type(rows[0].get('totalCount')) is not int or any(rows[0].get(k) != v for k, v in {
                        'blogId': blog, 'httpStatus': 200, 'path': '/PrePostListCount.naver',
                        'isSuccess': True, 'totalCount': count if version == '4' else 0,
                        'requestMethod': 'GET'}.items()):
                    return None
        return entries
    except (ValueError, KeyError, TypeError, AttributeError):
        return None
