"""Shared crew know-how policy: open to CEO links, YouTube/web fact-checks, and Radar autonomous study."""


def usable_knowhow(node):
    required = ('title', 'method', 'whenToUse')
    if not (node.get('type') == 'PracticalKnowHow' and node.get('active', True) is True
            and node.get('measurementStatus') == 'observed_procedure'
            and all(isinstance(node.get(key), str) and node[key].strip() for key in required)):
        return False
    try:
        _observed_method(node['method'], node.get('verifiedWorkProof'))
        return True
    except (OSError, ValueError, KeyError, TypeError):
        return False


def _observed_method(method, proof):
    from common.hermes_memory import verified_work_proof
    if not isinstance(proof, dict):
        raise ValueError('Host work receipt required')
    observed = verified_work_proof(proof)
    if not method.strip() or method.strip() not in observed.get('evidenceText', ''):
        raise ValueError('Procedure must be an exact excerpt of host-verified evidence')
    return observed


def record_knowhow(*, title, method, when_to_use, fact_check_summary='', limits='', source_url='', source_type='crew_fact_check', roles=None, tags=None, recorded_by='radar', verified_work_proof=None):
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
    if not all(isinstance(v, str) and v.strip() for v in (title, method, when_to_use)):
        raise ValueError('Title, method and applicability are required')
    if len(method) > 1500:
        raise ValueError('Procedure exceeds evidence excerpt limit')
    if verified_work_proof is not None:
        _observed_method(method, verified_work_proof)
    node = {
        'type': 'PracticalKnowHow',
        'active': True,
        'optional': True,
        'causalClaim': False,
        'measurementStatus': 'observed_procedure' if verified_work_proof is not None else 'hypothesis',
        'verifiedWorkProof': verified_work_proof,
        'evidenceScope': 'Observed procedure only; no ranking, longevity or revenue effect established',
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
        # Repeated model summaries must not overwrite an evidenced procedure.
        prior = graph.get('nodes', {}).get(ident)
        if verified_work_proof is None and prior and usable_knowhow(prior):
            return {'ok': True, 'id': ident, 'node': prior}
        graph.setdefault('nodes', {})[ident] = node
        write(path, graph)
    try:
        from dashboard.agents.synapse import refresh_once
        refresh_once(root, force=True)
    except Exception:
        pass
    return {'ok': True, 'id': ident, 'node': node}
