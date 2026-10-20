"""Bind visual approval to actual image bytes and their publication plans."""
import hashlib
import json
from pathlib import Path

VISUAL_SOURCES = ("generated", "capture", "original", "photo")

class MaterialRequired(RuntimeError):
    pass

def load_material_manifest(path=None, account=None, roots=None):
    if path:
        raise MaterialRequired("External material import requires a verified manifest implementation")
    return {}

def import_materials(packet=None, *args, **kwargs):
    if packet:
        raise MaterialRequired("External material import is not verified")
    return {}

def material_context(packet=None):
    return packet or {}

def bind_material_plans(plans=None, packet=None, folder=None):
    plans = plans or []
    if any(p.get("materialId") or p.get("source") != "generated" for p in plans):
        raise MaterialRequired("Capture/original plans require verified external materials")
    return plans

def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

def _image_hash(path):
    path = Path(path)
    if not path.is_file() or not path.stat().st_size:
        raise ValueError("Visual image is missing or empty")
    # Decode the actual file rather than accepting a filename or text placeholder.
    from PIL import Image
    with Image.open(path) as image:
        image.verify()
    return hashlib.sha256(path.read_bytes()).hexdigest()

def review_visual_groups(plans, paths, judge, context, directory, prefix, plan_focus=False):
    if len(plans) != len(paths):
        raise ValueError("Visual plan/image count mismatch")
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    schema = {"type": "object", "additionalProperties": False,
        "properties": {"passed": {"type": "boolean"}, "observation": {"type": "string"},
            "issues": {"type": "array", "items": {"type": "string"}}},
        "required": ["passed", "observation", "issues"]}
    records = []
    for index, (plan, path) in enumerate(zip(plans, paths)):
        digest = _image_hash(path)
        request = ("Inspect the attached actual image pixels against this publication plan and article. "
            "Describe what is visible. Reject misleading captions, topic mismatch, fabricated screenshot/"
            "firsthand claims, unreadable necessary details, and unsupported observations. Generated examples "
            "are allowed when honestly labeled. Separate optional aesthetic preferences and perfectly identical composition from substantive reader claims; uncertainty whether an illustrative figure is a mannequin or a person alone is not rejection evidence when no real-photography or firsthand-wear claim is made. Still reject visible failures of claimed solid color, subject type, hem/sock exposure, or caption promises. Return passed only when no substantive issues remain.\n" +
            json.dumps({"plan": plan, "context": context}, ensure_ascii=False))
        verdict = judge(request, [str(Path(path).resolve())], schema)
        destination = directory / f"{prefix}_{index}.json"
        destination.write_text(json.dumps({"version": 1, "status": "rejected", "imageSha256": digest,
            "planSha256": _digest(plan), "sourceObservations": bool(plan_focus),
            "review": verdict}, ensure_ascii=False, indent=2), encoding="utf-8")
        if (not isinstance(verdict, dict) or verdict.get("passed") is not True
                or verdict.get("issues") != [] or not str(verdict.get("observation") or "").strip()):
            raise ValueError("Actual image review rejected: " + json.dumps(verdict, ensure_ascii=False))
        if _image_hash(path) != digest:
            raise ValueError("Image changed during visual review")
        record = {"version": 1, "status": "approved", "imageSha256": digest, "planSha256": _digest(plan),
            "sourceObservations": bool(plan_focus), "review": verdict}
        destination = directory / f"{prefix}_{index}.json"
        record["file"] = str(destination.resolve())
        destination.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        records.append(record)
    return records

def verify_visual_records(plans, paths, records, source_observations=False):
    if len(plans) != len(paths) or not isinstance(records, list) or len(records) != len(plans):
        raise ValueError("Complete actual visual review records required")
    for plan, path, record in zip(plans, paths, records):
        if not isinstance(record, dict):
            raise ValueError("Invalid visual review record")
        verdict = record.get("review") or {}
        if (record.get("version") != 1 or record.get("status") != "approved" or record.get("imageSha256") != _image_hash(path)
                or record.get("planSha256") != _digest(plan)
                or record.get("sourceObservations") is not bool(source_observations)
                or verdict.get("passed") is not True or verdict.get("issues") != []
                or not str(verdict.get("observation") or "").strip()):
            raise ValueError("Visual review does not approve these exact image bytes and plan")
    return True

async def annotate_observed_materials(packet=None, *args, **kwargs):
    if packet:
        raise MaterialRequired("External material annotation is not verified")
    return {}
