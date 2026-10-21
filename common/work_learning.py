"""Bounded observed review metadata for verified-work learning, never article text."""
import json
from pathlib import Path

from common.hermes_memory import learning_text


FIELDS = frozenset(('issues', 'notes', 'selectionReason', 'purpose', 'status', 'passed',
                    'articleStructure', 'factualReview', 'corrections', 'repairReason',
                    'reason', 'sourceType', 'pcWholeDocumentVisualReview',
                    'mobileWholeDocumentVisualReview', 'categoryMatches'))
CONTAINERS = frozenset(('review', 'result', 'imagePlans', 'images', 'checks'))


def observed_review_summary(paths):
    """Return original bounded fields and the exact files supplying them; no inference."""
    records, used = [], []
    def select(value, depth=0):
        if depth > 4:
            return None
        if isinstance(value, list):
            return [item for entry in value[:12] if (item := select(entry, depth+1)) is not None]
        if not isinstance(value, dict):
            return None
        result = {}
        for key, item in value.items():
            if key in FIELDS:
                encoded = json.dumps(item, ensure_ascii=False)
                if len(encoded) <= 900 and 'http' not in encoded.lower():
                    try:
                        learning_text(encoded)
                    except ValueError:
                        continue
                    result[key] = item
            elif key in CONTAINERS:
                selected = select(item, depth+1)
                if selected:
                    result[key] = selected
        return result or None
    for source in paths:
        path = Path(source)
        if not path.is_file() or path.stat().st_size > 2_000_000:
            continue
        selected = select(json.loads(path.read_text(encoding='utf-8')))
        record = {'artifact':path.name, 'observed':selected}
        if selected and len(json.dumps(records+[record], ensure_ascii=False)) <= 6000:
            records.append(record)
            used.append(path)
    return json.dumps(records, ensure_ascii=False), used
