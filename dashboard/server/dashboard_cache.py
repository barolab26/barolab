"""Bounded single-flight caching for expensive read-only dashboard projections."""
from collections import OrderedDict
import threading
import time

from fastapi import HTTPException


def compact_metrics(data):
    """Gauge-only projection; preserve measured values, dates and uncertainty."""
    def pick(row, keys):
        return {key: row[key] for key in keys if key in row}
    analysis = data.get('trafficAnalysis') or {}
    sites = []
    for row in analysis.get('sites', []):
        ga4 = row.get('ga4') or {}
        compact = pick(ga4, ('status', 'checkedAt', 'timezone', 'source', 'stale', 'error', 'note'))
        compact['periods'] = {name: pick(period, ('start', 'end', 'users', 'sessions', 'pageViews',
            'provisional', 'limited')) for name, period in (ga4.get('periods') or {}).items()}
        sites.append({'site': row.get('site'), 'ga4': compact})
    return {**pick(data, ('checkedAt', 'indexing', 'traffic', 'revenue')),
        'sites': [pick(row, ('site', 'traffic')) for row in data.get('sites', [])],
        'contentAudit': pick(data.get('contentAudit') or {}, ('inventoryTotal', 'counts')),
        'trafficAnalysis': {**pick(analysis, ('checkedAt', 'today', 'timezone')),
            'sites': sites, 'naverBlogs': [pick(row, ('site', 'date', 'days', 'status', 'checkedAt', 'stale'))
                for row in analysis.get('naverBlogs', [])]}}


class ReadCache:
    def __init__(self, ttl=30, capacity=8):
        self.ttl = ttl
        self.capacity = capacity
        self.lock = threading.Lock()
        self.values = OrderedDict()
        self.building = set()

    def get(self, key, build):
        with self.lock:
            cached = self.values.get(key)
            if cached and time.monotonic() - cached[0] < self.ttl:
                self.values.move_to_end(key)
                return cached[1]
            # Never occupy the shared HTTP thread pool waiting for another
            # expensive projection. No stale result is presented as fresh.
            if key in self.building or len(self.building) >= self.capacity:
                raise HTTPException(503, '조회 자료를 갱신 중입니다.', headers={'Retry-After': '5'})
            self.building.add(key)
        try:
            value = build()
            with self.lock:
                self.values[key] = (time.monotonic(), value)
                self.values.move_to_end(key)
                while len(self.values) > self.capacity:
                    self.values.popitem(last=False)
            return value
        finally:
            with self.lock:
                self.building.discard(key)
