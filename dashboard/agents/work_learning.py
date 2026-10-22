"""One-pass publishing: research, document, format checks, submit, verify."""

import sys

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

sys.path.insert(0, str(BASE_DIR.parent))

import hashlib

import json

import time

from pathlib import Path

from common.collection_observability import locked, write

ROOT = Path(__file__).resolve().parents[2]

def read(path):
    try:
        path = Path(path)
        limit = 64000000 if path.name == 'editorial-memory-graph.json' else 3000000
        if path.stat().st_size > limit:
            return {}
        value = json.loads(path.read_text(encoding='utf-8-sig'))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}

def solution_evidence(folder):
    path = Path(folder) / 'editorial-lineage.json'
    chain = read(path).get('approvals', [])
    if not chain:
        return ('', [])
    paths = [path]
    summary = []
    for approval in chain[:4]:
        saved = Path(approval['approvalPath'])
        if hashlib.sha256(saved.read_bytes()).hexdigest() != approval['approvalSha256']:
            raise ValueError('Changed solution evidence')
        paths.append(saved)
        summary.append({'problem': approval.get('failureReason'), 'strategy': approval['step'], 'resolution': approval['approval']['reason'], 'newQuestion': approval['approval']['readerQuestion'], 'originalGoalSolved': approval.get('oldQuestionSolved', False)})
    return (' Observed supervised recovery (subject to the final public work verification): ' + json.dumps(summary, ensure_ascii=False)[:6000], paths)

def learn_public(folder, proof, project, identity, root=ROOT, public_url='', vault_event_id='', vault_status='', _graph_key=None):
    """The existing strict producer proof is required, not a bare HTTP 200."""
    from common.hermes_memory import verified_work_proof
    verified = verified_work_proof(proof)
    if verified.get('outcome') not in ('public_verified', 'public_naver_verified', 'public_answer_verified'):
        raise ValueError('A reservation or preparation cannot produce a public outcome')
    chain = read(Path(folder) / 'editorial-lineage.json').get('approvals', [])
    if not chain:
        return None
    if not public_url.startswith('https://'):
        raise ValueError('Verified final public URL required')
    if isinstance(verified.get('artifactHashes'), list) and (not any((Path(a['path']).resolve() == (Path(folder) / 'editorial-lineage.json').resolve() for a in verified['artifactHashes']))):
        return complete_resolution_learning(folder, proof, project, identity, public_url, root, graph_key=_graph_key or hashlib.sha256(json.dumps(proof, sort_keys=True).encode()).hexdigest())
    path = Path(root) / 'dashboard/data/editorial-memory-graph.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    key = _graph_key or hashlib.sha256(json.dumps(proof, sort_keys=True).encode()).hexdigest()
    with locked(path.parent / 'editorial-memory.lock'):
        graph = read(path)
        if path.exists() and (not graph):
            raise ValueError('Preserve unreadable knowledge graph')
        graph = graph or {'schema': 'editorial-memory-graph-v1', 'nodes': {}, 'edges': []}
        for index, approval in enumerate(chain):
            saved = Path(approval['approvalPath'])
            if hashlib.sha256(saved.read_bytes()).hexdigest() != approval['approvalSha256']:
                raise ValueError('Changed recovery approval')
            prefix = f'{key}:{index}'
            problem = prefix + ':problem'
            resolution = prefix + ':resolution'
            outcome = prefix + ':outcome'
            episode_id = hashlib.sha256((public_url + '|' + approval['approvalSha256']).encode()).hexdigest()
            pattern = 'problem-pattern:' + hashlib.sha256((project + '|' + str(approval.get('topicCategory', '')) + '|' + approval['step']).encode()).hexdigest()
            aggregate = graph['nodes'].setdefault(pattern, {'type': 'ProblemPattern', 'project': project, 'strategy': approval['step'], 'resolvedCount': 0, 'concreteExamples': []})
            if not any((e.get('episodeId') == episode_id for e in aggregate['concreteExamples'])):
                aggregate['concreteExamples'].append({'episodeId': episode_id, 'domain': identity, 'slug': public_url.rstrip('/').split('/')[-1], 'keywordOrEvidence': approval['approval'].get('readerQuestion', ''), 'resolution': approval['approval']['reason'], 'publicUrl': public_url, 'resolvedAt': time.time()})
                aggregate['resolvedCount'] += 1
                aggregate['lastResolvedAt'] = time.time()
            pattern_edge = {'source': pattern, 'target': problem, 'type': 'concrete_episode'}
            if pattern_edge not in graph['edges']:
                graph['edges'].append(pattern_edge)
            graph['nodes'][problem] = {'type': 'Problem', 'project': project, 'identity': identity, 'category': approval.get('topicCategory', ''), 'stage': 'researcher -> writer', 'originalQuestion': approval['originalQuestion'], 'reason': approval.get('failureReason'), 'evidence': approval['originalHashes']}
            graph['nodes'][resolution] = {'type': 'Resolution', 'agents': approval.get('agents', ['jarvis', 'radar', 'publi']), 'strategy': approval['step'], 'reason': approval['approval']['reason'], 'question': approval['approval']['readerQuestion'], 'approvalSha256': approval['approvalSha256']}
            graph['nodes'][outcome] = {'type': 'Outcome', 'verifiedWorkProof': proof, 'publicationUrl': public_url, 'elapsedSeconds': max(0, time.time() - approval['approvedAt']), 'publicEvidence': {k: verified.get(k) for k in ('channel', 'outcome', 'sourceAgent')}, 'indexing': graph['nodes'].get(outcome, {}).get('indexing'), 'traffic': graph['nodes'].get(outcome, {}).get('traffic'), 'revenue': graph['nodes'].get(outcome, {}).get('revenue'), 'measurementState': graph['nodes'].get(outcome, {}).get('measurementState', 'awaiting_trace_measurement')}
            for source, target, label in ((problem, resolution, 'resolved_by'), (resolution, outcome, 'verified_by')):
                edge = {'source': source, 'target': target, 'type': label}
                if edge not in graph['edges']:
                    graph['edges'].append(edge)
            if vault_event_id:
                vault = key + ':vault'
                graph['nodes'][vault] = {'type': 'VaultReference', 'eventId': vault_event_id, 'status': vault_status, 'source': 'Hermes verified work intake'}
                edge = {'source': outcome, 'target': vault, 'type': 'learning_intake'}
                if edge not in graph['edges']:
                    graph['edges'].append(edge)
        write(path, graph)
    return key

def complete_resolution_learning(folder, original_proof, project, identity, public_url, root=ROOT, graph_key=None):
    """Upgrade an in-flight old producer without changing its immutable public receipt."""
    from common.hermes_memory import verified_work_proof, write_verified_work_receipt
    from common.llm_client import record_verified_work
    observed = verified_work_proof(original_proof)
    text, paths = solution_evidence(folder)
    if not paths:
        return None
    receipt = Path(folder) / 'editorial-learning-receipt.json'
    if receipt.exists():
        proof = {'sourceRef': str(receipt.resolve()), 'sourceSha256': hashlib.sha256(receipt.read_bytes()).hexdigest()}
        verified_work_proof(proof)
    else:
        artifacts = list(observed['artifactHashes'])
        seen = {Path(a['path']).resolve() for a in artifacts}
        artifacts += [{'path': str(p.resolve()), 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()} for p in paths if p.resolve() not in seen]
        proof = write_verified_work_receipt(receipt, work_type='verified_work_receipt_v1', channel=observed['channel'], outcome=observed['outcome'], scope=observed['outcome'], source_agent='publi', evidence_text=observed['evidenceText'] + text, artifacts=artifacts, checks=observed['verification']['checks'])
    event_id = 'editorial:' + hashlib.sha256((original_proof['sourceSha256'] + proof['sourceSha256']).encode()).hexdigest()
    intake = record_verified_work(event_id, proof)
    return learn_public(folder, proof, project, identity, root, public_url=public_url, vault_event_id=event_id, vault_status=intake.get('state') or ('pending' if intake.get('queued') else 'existing'), _graph_key=graph_key)

def lessons(project, identity, root=ROOT, category=''):
    graph = read(Path(root) / 'dashboard/data/editorial-memory-graph.json')
    nodes = graph.get('nodes', {})
    result = []
    from common.hermes_memory import verified_work_proof
    checked = {}

    def valid_outcome(key):
        node = nodes.get(key, {})
        if node.get('type') != 'Outcome':
            return False
        source = node.get('verifiedWorkProof') or {}
        identity = (source.get('sourceRef'), source.get('sourceSha256'))
        if identity in checked:
            return checked[identity]
        try:
            proof = verified_work_proof(source)
            checked[identity] = proof.get('outcome') in ('public_verified', 'public_naver_verified', 'public_answer_verified')
        except (OSError, ValueError, KeyError):
            checked[identity] = False
        return checked[identity]
    candidates = [e for e in graph.get('edges', []) if e.get('type') == 'resolved_by' and nodes.get(e.get('source'), {}).get('project') == project and (nodes.get(e.get('source'), {}).get('identity') == identity)]
    for edge in candidates[-20:]:
        problem = nodes.get(edge.get('source'), {})
        resolution = nodes.get(edge.get('target'), {})
        if edge.get('type') == 'resolved_by' and problem.get('project') == project and (problem.get('identity') == identity) and (not category or not problem.get('category') or problem['category'] == category) and any((e.get('source') == edge['target'] and e.get('type') == 'verified_by' and valid_outcome(e.get('target')) for e in graph.get('edges', []))):
            result.append({'previousProblem': problem.get('originalQuestion'), 'strategy': resolution.get('strategy'), 'lesson': resolution.get('reason'), 'measurements': [{'indexing': nodes[e['target']].get('indexing'), 'traffic': nodes[e['target']].get('traffic'), 'revenue': nodes[e['target']].get('revenue')} for e in graph.get('edges', []) if e.get('source') == edge['target'] and e.get('type') == 'verified_by' and (e.get('target') in nodes)], 'scope': 'Prior verified outcome; acquire current facts independently. Null measurement means unknown. Revenue attribution is not a causal uplift claim.'})
    return result[-5:]

def learn_naver_public(attempt, public):
    from common.hermes_memory import write_verified_work_receipt
    from common.llm_client import record_verified_work
    from dashboard.collectors.naver_public import verify_public_body
    from urllib.parse import urlsplit
    folder = Path(attempt.get('artifactFolder') or '').resolve()
    if not folder.is_relative_to((ROOT / 'naver_blog_posting/output').resolve()) or not read(folder / 'editorial-lineage.json'):
        return
    reservation = read(folder / 'reservation-evidence.json')
    saved = folder / 'reserved-server-document.json'
    if reservation.get('submissionStatus') != 'verified_reserved' or not saved.is_file() or reservation.get('account') != attempt.get('account') or (reservation.get('title') != public.get('title')) or (str(reservation.get('reserveTime', ''))[:10] != public.get('publicationDate')):
        return
    url = urlsplit(public.get('publicUrl', ''))
    if url.scheme != 'https' or url.hostname != 'blog.naver.com' or url.path.strip('/').split('/')[0] != reservation.get('blogId'):
        return
    receipt = folder / 'editorial-public-receipt.json'
    if receipt.exists():
        proof = {'sourceRef': str(receipt), 'sourceSha256': hashlib.sha256(receipt.read_bytes()).hexdigest()}
    else:
        observed = verify_public_body(public['publicUrl'], folder)
        if observed.get('publicHttpStatus') != 200 or observed.get('publicBodyMatched') is not True or observed.get('bodyParagraphsMatch') is not True:
            return
        expected = {key: reservation[key] for key in ('account', 'title', 'reserveTime', 'documentSha256')}
        expected.update(savedDocumentPath=str(saved), savedDocumentSha256=hashlib.sha256(saved.read_bytes()).hexdigest())
        completion = folder / 'editorial-public-verification.json'
        write(completion, {'type': 'naver_public_completion_v1', 'expected': expected, 'observation': {**public, **observed, 'publicPublicationVerified': True}, 'checkedAt': time.time()})
        paths = [completion, folder / 'reservation-evidence.json', saved]
        recovery_text, recovery_paths = solution_evidence(folder)
        paths += recovery_paths
        proof = write_verified_work_receipt(receipt, work_type='verified_work_receipt_v1', channel='naver_blog', outcome='public_naver_verified', scope='public_naver_verified', source_agent='publi', evidence_text='Actual public identity and saved submitted Naver document matched after supervised replanning.' + recovery_text, artifacts=[{'path': str(p), 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()} for p in paths], checks=[{'type': kind, 'passed': True, 'evidenceRef': str(completion)} for kind in ('public_identity', 'public_content')])
    learning = record_verified_work(f'naver:{folder}:public-verified-work', proof)
    learn_public(folder, proof, 'naver_blog', attempt['account'], public_url=public['publicUrl'], vault_event_id=f'naver:{folder}:public-verified-work', vault_status=learning.get('state') or ('pending' if learning.get('queued') else 'existing'))

def refresh_measurements(root=ROOT):
    """Attach exact-URL observations only; never allocate site-wide AdSense totals."""
    path = Path(root) / 'dashboard/data/editorial-memory-graph.json'
    graph = read(path)
    if not graph:
        return
    references = [node for node in graph.get('nodes', {}).values() if node.get('type') == 'VaultReference' and node.get('eventId')]
    if references:
        try:
            from common.hermes_memory import _store
            updates = {}
            with _store.db() as db:
                for node in references:
                    row = db.execute('SELECT state,detail FROM learning_candidates WHERE event_id=?', (node['eventId'],)).fetchone()
                    if row:
                        updates[node['eventId']] = {'status': row['state'], 'memoryId': row['detail'] if row['state'] == 'approved' else None}
            with locked(path.parent / 'editorial-memory.lock'):
                current = read(path)
                for node in current.get('nodes', {}).values():
                    if node.get('type') == 'VaultReference' and node.get('eventId') in updates:
                        node.update(updates[node['eventId']])
                if current:
                    write(path, current)
        except (OSError, ValueError):
            pass
    evidence = []
    for relative in ('dashboard/data/indexing-submissions.json', 'dashboard/data/public/metrics.json', 'dashboard/data/kin-measurement.json', 'dashboard/data/metrics.json'):
        document = read(Path(root) / relative)

        def visit(value):
            if isinstance(value, dict):
                url = value.get('publicUrl') or value.get('url') or value.get('answer_url') or value.get('pagePath')
                if isinstance(url, str) and url.startswith('https://'):
                    measured = {k: value[k] for k in ('indexed', 'indexStatus', 'clicks', 'impressions', 'sessions', 'pageViews', 'revenue', 'revenueUsd', 'revenueVerified') if k in value and isinstance(value[k], (str, int, float, bool))}
                    if measured:
                        evidence.append((url, relative, measured, document.get('checkedAt')))
                for child in value.values():
                    visit(child)
            elif isinstance(value, list):
                for child in value:
                    visit(child)
        visit(document)
    if not evidence:
        return
    with locked(path.parent / 'editorial-memory.lock'):
        graph = read(path)
        if not graph:
            return
        for node in graph.get('nodes', {}).values():
            if node.get('type') != 'Outcome':
                continue
            matched = [{'source': source, 'sourceCheckedAt': at, 'scope': 'exact_url', 'values': values} for url, source, values, at in evidence if url == node.get('publicationUrl')]
            if matched:
                node.update(measurementEvidence=matched, measurementLinkedAt=time.time(), measurementState='exact_url_observed')
                for item in matched:
                    values = item['values']
                    if 'indexed' in values or 'indexStatus' in values:
                        node['indexing'] = item
                    if any((k in values for k in ('clicks', 'impressions', 'sessions', 'pageViews'))):
                        node['traffic'] = item
                    if values.get('revenueVerified') is True and any((k in values for k in ('revenue', 'revenueUsd'))):
                        node['revenue'] = item
        write(path, graph)
