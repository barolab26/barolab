"""Keep exact historical evidence on disk without loading every old snapshot."""
import hashlib
import json
from pathlib import Path
import re

MARKER = '__archivedObservationResult'
SOURCE_FIELDS = ('source', 'sha256', 'available', 'status', 'ok')


class ArchivedResult(dict):
    """JSON exposes an explicit excerpt; keyed reads retrieve verified source data."""
    def __init__(self, metadata=None, folder=None):
        super().__init__(metadata or {})
        self.folder = folder

    def read(self):
        identity = dict.__getitem__(self, MARKER)
        if not re.fullmatch(r'[a-f0-9]{64}', identity):
            raise ValueError('Invalid archived observation identity')
        path = Path(self.folder) / (identity + '.json')
        if path.is_symlink() or path.parent.is_symlink() or path.stat().st_size > 32_000_000:
            raise ValueError('Unsafe or oversized archived observation')
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != identity:
            raise ValueError('Archived observation hash mismatch')
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError('Archived observation must be an object')
        return value

    def __getitem__(self, key):
        # Excerpt metadata must never shadow an original source field.
        if key == MARKER or (key in SOURCE_FIELDS and dict.__contains__(self, key)):
            return dict.__getitem__(self, key)
        return self.read()[key]

    def get(self, key, default=None):
        if key == MARKER or (key in SOURCE_FIELDS and dict.__contains__(self, key)):
            return dict.get(self, key, default)
        return self.read().get(key, default)

    def __contains__(self, key):
        return key == MARKER or key in self.read()


def hydrate(row, folder):
    if isinstance(row, dict):
        for event in row.get('observations', []):
            result = event.get('result')
            if isinstance(result, dict) and MARKER in result and not isinstance(result, ArchivedResult):
                event['result'] = ArchivedResult(result, folder)
    return row


def materialize(value):
    return value.read() if isinstance(value, ArchivedResult) else value


def source_values(value, batch=False):
    if isinstance(value, ArchivedResult):
        return [{'source': p} for p in dict.get(value, 'archiveSources', [])]
    return value.values() if batch and isinstance(value, dict) else [value]


def compact(row, folder):
    """Preserve event IDs/hashes and all execution receipts; archive large old reads."""
    from common.dashboard_jobs import atomic_text
    for event in row.get('observations', [])[:-12]:
        value = event.get('result')
        if event.get('tool') not in ('projects', 'evidence', 'evidence_batch', 'read_source'):
            continue
        if not isinstance(value, dict) or isinstance(value, ArchivedResult) or MARKER in value:
            continue
        raw = json.dumps(value, sort_keys=True, ensure_ascii=False).encode('utf-8')
        if len(raw) < 8192:
            continue
        identity = hashlib.sha256(raw).hexdigest()
        path = Path(folder) / (identity + '.json')
        if path.parent.is_symlink() or path.is_symlink():
            raise ValueError('Symlink observation archive denied')
        if path.exists():
            if hashlib.sha256(path.read_bytes()).hexdigest() != identity:
                raise ValueError('Existing observation archive hash mismatch')
        else:
            atomic_text(path, raw.decode('utf-8'), durable=True)
        excerpt = {k: v for k, v in value.items()
                   if k in SOURCE_FIELDS and isinstance(v, (str, bool, int, float, type(None)))}
        sources = source_values(value, event['tool'] == 'evidence_batch')
        excerpt['archiveSources'] = sorted({v['source'] for v in sources if isinstance(v, dict)
                                           and isinstance(v.get('source'), str) and v['source'].endswith('.json')})
        excerpt.update({MARKER: identity, 'detailRequired': True, 'payloadBytes': len(raw),
                        'readWith': {'name': 'observation:' + event['id']}})
        event['result'] = ArchivedResult(excerpt, folder)
