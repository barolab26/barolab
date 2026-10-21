"""Collect read-only connection-repair evidence without Git author metadata."""

import hashlib
import json
import sqlite3
import subprocess
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path


def _database_snapshot(path):
    with sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True) as db:
        tables = [r[0] for r in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        result = {}
        for table in tables:
            name = '"' + table.replace('"', '""') + '"'
            rows = db.execute('SELECT * FROM ' + name).fetchall()
            result[table] = {'rows': len(rows), 'sha256': hashlib.sha256(
                repr(sorted(map(repr, rows))).encode()).hexdigest()}
        return result


def collect_connection_repair(root, folder, commit, source_paths, endpoint,
                              databases, previous_failure):
    folder = (Path(folder) if folder is not None else
              Path.home() / '.barolab' / 'memories' / 'work-evidence' /
              ('connection-repair-' + uuid.uuid4().hex))
    folder.mkdir(parents=True, exist_ok=False)
    # Author emails and unrelated commit metadata are not learning material.
    diff = subprocess.check_output(
        ['git', 'show', '--format=', commit, '--', *source_paths], cwd=root)
    (folder / 'source.diff').write_bytes(diff)
    before = {str(p): _database_snapshot(p) for p in databases}
    with urllib.request.urlopen(endpoint, timeout=20) as response:
        data = json.load(response)
        observation = {'status': response.status,
                       'contractVersion': data.get('contractVersion'),
                       'nodes': len(data['nodes']), 'edges': len(data['edges'])}
    after = {str(p): _database_snapshot(p) for p in databases}
    proof = {'version': 1, 'observedAt': datetime.now(timezone.utc).isoformat(),
             'commit': subprocess.check_output(
                 ['git', 'rev-parse', commit], cwd=root, text=True).strip(),
             'sourceDiffPath': str(folder / 'source.diff'),
             'sourceDiffSha256': hashlib.sha256(diff).hexdigest(),
             'http': observation,
             'dbReadOnlyCheck': {'unchanged': before == after,
                                'before': before, 'after': after},
             'previousFailureEvidence': previous_failure,
             'scope': 'Source, HTTP and DB checks only; no UI outcome inferred'}
    path = folder / 'repair-proof.json'
    path.write_text(json.dumps(proof, ensure_ascii=False, indent=2), encoding='utf-8')
    return path
