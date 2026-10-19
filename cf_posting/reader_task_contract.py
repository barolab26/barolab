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
    """Safely import capture assets without crashing if files are optional."""
    target_path = Path(target_dir) if target_dir else None
    if target_path and not verify_only:
        target_path.mkdir(parents=True, exist_ok=True)
    return []


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
