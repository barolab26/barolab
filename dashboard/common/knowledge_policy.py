"""Shared crew know-how policy: open to CEO links, YouTube/web fact-checks, and Radar autonomous study."""


def usable_knowhow(node):
    required = ('title', 'method', 'whenToUse')
    return (node.get('type') == 'PracticalKnowHow' and node.get('active', True) is True
            and all(isinstance(node.get(key), str) and node[key].strip() for key in required))


def record_knowhow(*, title, method, when_to_use, fact_check_summary='', limits='', source_url='', source_type='crew_fact_check', roles=None, tags=None, recorded_by='radar'):
    import datetime as dt
    import hashlib
    from pathlib import Path
    from common.collection_observability import load, write, locked
    root = Path(__file__).resolve().parents[2]
    data = root / 'dashboard/data'
    path = data / 'editorial-memory-graph.json'
    roles = list(roles or ['jarvis', 'publi', 'radar', 'doctor', 'trace', 'patch'])
    tags = list(tags or [])
    ident = 'knowhow:' + hashlib.sha256((str(title).strip() + '|' + str(source_url).strip()).encode('utf-8')).hexdigest()[:20]
    now_iso = dt.datetime.now(dt.timezone.utc).isoformat()
    node = {
        'type': 'PracticalKnowHow',
        'active': True,
        'optional': True,
        'causalClaim': False,
        'measurementStatus': 'verified_fact_checked' if fact_check_summary else 'not_measured',
        'sourceType': source_type,
        'sourceUrl': str(source_url or ''),
        'recordedBy': recorded_by,
        'recordedAt': now_iso,
        'title': str(title).strip()[:200],
        'originalText': str(fact_check_summary or method).strip()[:1500],
        'factCheckSummary': str(fact_check_summary or '').strip()[:1500],
        'method': str(method).strip()[:1500],
        'whenToUse': str(when_to_use).strip()[:600],
        'limits': str(limits or '허위 수치·과장 금지, 실제 원문 근거와 결합하여 적용').strip()[:600],
        'roles': roles,
        'tags': tags,
    }
    with locked(data):
        graph = load(path) or {'nodes': {}, 'edges': []}
        graph.setdefault('nodes', {})[ident] = node
        write(path, graph)
    try:
        from dashboard.agents.synapse import refresh_once
        refresh_once(root, force=True)
    except Exception:
        pass
    return {'ok': True, 'id': ident, 'node': node}
