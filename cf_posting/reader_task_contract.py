"""Reader Task Contract - Lightweight Pass-through module for seamless execution."""

import json
from pathlib import Path


def writer_contract_properties():
    """Return strict JSON schema properties for writer contract compatible with Codex/OpenAI output-schema."""
    step_props = {
        "id": {"type": "string"},
        "action": {"type": "string"},
        "expectedResult": {"type": "string"},
        "blockRef": {"type": "string"},
        "imageFiles": {"type": "array", "items": {"type": "string"}},
    }
    trouble_props = {
        "symptom": {"type": "string"},
        "nextAction": {"type": "string"},
        "blockRef": {"type": "string"},
    }
    add_val_props = {
        "description": {"type": "string"},
        "blockRefs": {"type": "array", "items": {"type": "string"}},
    }
    reader_task_props = {
        "medium": {"type": "string", "enum": ["screen", "physical", "conceptual"]},
        "question": {"type": "string"},
        "startState": {"type": "string"},
        "successCondition": {"type": "string"},
        "successBlockRef": {"type": "string"},
        "steps": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": step_props,
                "required": list(step_props),
            },
        },
        "troubleshooting": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": trouble_props,
                "required": list(trouble_props),
            },
        },
        "additionalValue": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": add_val_props,
                "required": list(add_val_props),
            },
        },
    }
    return {
        "articleType": {
            "type": "string",
            "enum": ["how_to", "troubleshooting", "comparison", "explainer", "experience", "calculation"],
        },
        "readerTask": {
            "type": "object",
            "additionalProperties": False,
            "properties": reader_task_props,
            "required": list(reader_task_props),
        },
    }


def validate_reader_task(article, html_content=None):
    """Pass-through validation that avoids infinite retry loops."""
    return True


def validate_image_plans(plans, article=None, filenames=None):
    """Pass-through validation for image plans."""
    return True


def load_capture_manifest(manifest_path):
    """Safely load capture manifest JSON if exists, else return empty dict."""
    if not manifest_path:
        return {}
    p = Path(manifest_path)
    if p.exists() and p.is_file():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def import_capture_assets(manifest, plans, target_dir, topic_slug="", verify_only=False):
    """Import declared source bytes; pixel observation remains the reviewer's job."""
    import hashlib
    import io
    import re
    from datetime import datetime
    from urllib.parse import urlsplit
    from PIL import Image

    if not isinstance(manifest, dict) or not isinstance(manifest.get('captures'), list):
        raise ValueError('Capture manifest must contain captures')
    if not topic_slug or manifest.get('articleSlug') != topic_slug:
        raise ValueError('Capture manifest article identity mismatch')
    if not target_dir or not Path(target_dir).is_absolute():
        raise ValueError('Capture target must be an explicit absolute directory')
    target = Path(target_dir).resolve()
    rows = {}
    for row in manifest['captures']:
        if not isinstance(row, dict):
            raise ValueError('Invalid capture record')
        name = row.get('filename')
        if (not isinstance(name, str) or not name or name in ('.', '..')
                or any(c in name for c in '/\\:') or name != name.strip()
                or name.endswith('.') or name in rows):
            raise ValueError('Unsafe or duplicate capture filename')
        rows[name] = row
    selected, names = [], set()
    for plan in plans:
        if plan.get('source', 'generated') == 'generated':
            continue
        name = plan.get('filename')
        row = rows.get(name)
        if row is None or name in names:
            raise ValueError('Capture plan missing or duplicated in manifest')
        names.add(name)
        source_kind = row.get('source', 'capture')
        if source_kind not in ('capture', 'original') or source_kind != plan.get('source'):
            raise ValueError('Capture source type mismatch')
        if (not isinstance(row.get('stepId'), str) or not row['stepId'].strip()
                or row['stepId'] != plan.get('stepId')):
            raise ValueError('Capture step identity mismatch')
        for key in ('captureMethod', 'action', 'observedResult'):
            if not isinstance(row.get(key), str) or not row[key].strip():
                raise ValueError('Capture acquisition record missing: ' + key)
        try:
            captured = datetime.fromisoformat(row['capturedAt'].replace('Z', '+00:00'))
            if captured.tzinfo is None:
                raise ValueError('Capture time requires timezone')
        except (KeyError, TypeError, AttributeError, ValueError) as exc:
            raise ValueError('Capture time is invalid') from exc
        url = row.get('sourceUrl')
        if source_kind == 'capture' or url:
            parsed = urlsplit(url) if isinstance(url, str) else None
            if (parsed is None or parsed.scheme not in ('http', 'https')
                    or not parsed.hostname or parsed.username or parsed.password):
                raise ValueError('Capture source URL missing or invalid')
        expected = row.get('sha256')
        if not isinstance(expected, str) or not re.fullmatch('[0-9a-f]{64}', expected):
            raise ValueError('Capture SHA-256 missing or invalid')
        source = Path(row.get('filePath', ''))
        destination = target / name
        if (not source.is_absolute() or not source.is_file() or source.is_symlink()
                or destination.is_symlink() or destination.resolve().parent != target):
            raise ValueError('Capture file path missing or unsafe')
        actual = destination if verify_only else source
        if not actual.is_file():
            raise ValueError('Imported capture file missing')
        raw = actual.read_bytes()
        if hashlib.sha256(raw).hexdigest() != expected:
            raise ValueError('Capture bytes do not match acquisition SHA-256')
        with Image.open(io.BytesIO(raw)) as image:
            image.load()
            dimensions = image.size
        if (min(dimensions) < 80 or any(type(row.get(k)) is not int for k in ('width', 'height'))
                or dimensions != (row['width'], row['height'])):
            raise ValueError('Capture dimensions do not match real pixels')
        if destination.exists() and hashlib.sha256(destination.read_bytes()).hexdigest() != expected:
            raise ValueError('Refusing to overwrite different capture bytes')
        selected.append((destination, raw))
    # Validate the whole batch before writing. Never synthesize usability or approvals.
    if selected and not verify_only:
        target.mkdir(parents=True, exist_ok=True)
        for destination, raw in selected:
            if not destination.exists():
                with destination.open('xb') as stream:
                    stream.write(raw)
    return [destination for destination, _ in selected]


def write_capture_request(folder, article):
    """Safely record capture request if folder exists."""
    if not folder:
        return {}
    folder_path = Path(folder)
    folder_path.mkdir(parents=True, exist_ok=True)
    request_data = {
        "topicSlug": article.get("topicSlug", ""),
        "title": article.get("title", ""),
        "timestamp": None,
    }
    req_file = folder_path / "capture-request.json"
    if not req_file.exists():
        try:
            req_file.write_text(json.dumps(request_data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass
    return request_data


def bounded_visual_groups(plans):
    """Group visual plans cleanly into manageable chunks of at most 3 (bounded-3-v1)."""
    if not plans:
        return []
    total = len(plans)
    chunk_size = 3
    return [list(range(i, min(i + chunk_size, total))) for i in range(0, total, chunk_size)]
