"""Bind visual approval to actual image bytes and their publication plans."""
import hashlib
import json
from pathlib import Path

VISUAL_SOURCES = ("generated", "capture", "original", "photo")

class MaterialRequired(RuntimeError):
    pass

def _inside(path, roots):
    path = Path(path).resolve()
    return any(path.is_relative_to(Path(root).resolve()) for root in roots)


def _capture_packet(packet, account=None, roots=None):
    from datetime import datetime, timezone
    from urllib.parse import urlsplit, parse_qs
    import re
    if not isinstance(packet, dict) or packet.get("version") != 1:
        raise MaterialRequired("Unsupported capture manifest")
    owner = packet.get("account")
    if not isinstance(owner, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", owner) or (account and owner != account):
        raise MaterialRequired("Capture account mismatch")
    if not str(packet.get("readerQuestion") or "").strip():
        raise MaterialRequired("Capture reader question required")
    rows = packet.get("materials")
    if not isinstance(rows, list) or not rows or len(rows) > 12:
        raise MaterialRequired("Bounded capture list required")
    seen = set()
    filenames = set()
    for row in rows:
        if not isinstance(row, dict) or row.get("source") != "capture":
            raise MaterialRequired("Only verified official captures are supported")
        mid, name = row.get("materialId", ""), row.get("filename", "")
        if not re.fullmatch(r"[A-Za-z0-9_-]+", mid) or mid in seen:
            raise MaterialRequired("Unique capture materialId required")
        seen.add(mid)
        if not re.fullmatch(r"[A-Za-z0-9_-]+\.(png|jpg|jpeg)", name):
            raise MaterialRequired("Unsafe capture filename")
        if name.lower() in filenames or not re.fullmatch(r"[A-Za-z0-9_-]+", str(row.get('stepId', ''))):
            raise MaterialRequired("Unique filenames and explicit stepId required")
        filenames.add(name.lower())
        path = Path(row.get("filePath", ""))
        if not path.is_absolute() or (roots and not _inside(path, [Path(r) / owner for r in roots])):
            raise MaterialRequired("Capture path outside account roots")
        try:
            actual = _image_hash(path)
            from PIL import Image
            with Image.open(path) as image:
                expected_format = 'PNG' if name.endswith('.png') else 'JPEG'
                if image.format != expected_format:
                    raise ValueError('Capture encoding must match PNG/JPEG filename')
        except (OSError, ValueError) as exc:
            raise MaterialRequired("Capture image cannot be decoded") from exc
        if row.get("sha256") != actual:
            raise MaterialRequired("Capture bytes changed")
        url = urlsplit(str(row.get("sourceUrl") or ""))
        host = (url.hostname or "").lower()
        if (url.scheme != "https" or url.username or url.password or url.port not in (None, 443)
                or not (host.endswith(".go.kr") or host in ("nhis.or.kr", "www.nhis.or.kr", "longtermcare.or.kr", "www.longtermcare.or.kr"))
                or any(re.search(r"token|password|secret|credential|session", k, re.I) for k in parse_qs(url.query))):
            raise MaterialRequired("Public official source URL required")
        try:
            captured = datetime.fromisoformat(row.get("capturedAt", "").replace("Z", "+00:00"))
            if captured.tzinfo is None or captured > datetime.now(timezone.utc):
                raise ValueError("Invalid capture time")
        except (TypeError, ValueError) as exc:
            raise MaterialRequired("Observed capture timestamp required") from exc
        if row.get("sensitiveDataAbsent") is not True or not str(row.get("observation") or "").strip():
            raise MaterialRequired("Capture observation and privacy declaration required")
    expected = _digest({k: v for k, v in packet.items() if k != "manifestSha256"})
    if packet.get("manifestSha256") not in (None, expected):
        raise MaterialRequired("Capture manifest changed")
    return {**packet, "manifestSha256": expected}


def load_material_manifest(path=None, account=None, roots=None):
    if not path:
        return {}
    try:
        source = Path(path)
        if not roots or not account or not _inside(source, [Path(r) / account for r in roots]):
            raise MaterialRequired("Manifest outside account roots")
        packet = json.loads(source.read_text(encoding="utf-8-sig"))
        return _capture_packet(packet, account, roots)
    except (OSError, ValueError, TypeError) as exc:
        raise MaterialRequired("Invalid capture manifest") from exc


def _copy_exact(source, destination, expected):
    source, destination = Path(source), Path(destination)
    if destination.is_symlink():
        raise MaterialRequired("Capture destination is a symlink")
    if _image_hash(source) != expected:
        raise MaterialRequired("Capture changed before copying")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if _image_hash(destination) != expected:
            raise MaterialRequired("Existing capture destination differs")
    else:
        with destination.open("xb") as stream:
            stream.write(source.read_bytes())
    if _image_hash(destination) != expected:
        raise MaterialRequired("Capture copy hash mismatch")


def import_materials(packet=None, folder=None):
    if not packet:
        return {}
    from copy import deepcopy
    packet = deepcopy(_capture_packet(packet))
    folder = Path(folder).resolve()
    if (folder / 'materials-manifest.json').is_symlink():
        raise MaterialRequired("Capture manifest destination is a symlink")
    if packet['account'] not in folder.parts:
        raise MaterialRequired("Capture destination account mismatch")
    for row in packet['materials']:
        target = folder / 'materials' / row['filename']
        if not _inside(target, [folder]):
            raise MaterialRequired("Capture destination escaped run")
        _copy_exact(row['filePath'], target, row['sha256'])
        row['filePath'] = str(target.resolve())
    packet.pop('manifestSha256', None)
    packet = _capture_packet(packet)
    (folder / 'materials-manifest.json').write_text(json.dumps(packet, ensure_ascii=False, indent=2), encoding='utf-8')
    return packet


def material_context(packet=None):
    if not packet:
        return {}
    return {**packet, 'materials': [{k: v for k, v in row.items() if k != 'filePath'} for row in packet['materials']]}


def bind_material_plans(plans=None, packet=None, folder=None):
    plans = plans or []
    records = {row['materialId']: row for row in _capture_packet(packet)['materials']} if packet else {}
    for plan in plans:
        if plan.get('source') == 'generated' and not plan.get('materialId'):
            continue
        row = records.get(plan.get('materialId'))
        if not row or any(plan.get(k) != row.get(k) for k in ('source', 'filename', 'stepId')):
            raise MaterialRequired("Capture plan must bind exact supplied material")
        if folder:
            target = Path(folder) / 'images' / row['filename']
            if not _inside(target, [folder]):
                raise MaterialRequired("Capture plan destination escaped run")
            _copy_exact(row['filePath'], target, row['sha256'])
    return plans


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def visual_prompt(plan, generated_default):
    """A captured source is copied, never described as a generation request."""
    if plan.get('materialId') or plan.get('source') != 'generated':
        return ''
    return str(plan.get('prompt') or '').strip() or generated_default

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
        request = ("Inspect the attached actual image pixels against THIS image's publication plan. "
            "The article is context, not a requirement for one image to depict every article section. "
            "Use publicationPlans to identify which claims belong to other images. Do not reject this image "
            "solely because a different image's assigned subject is absent. Still reject every unsupported "
            "claim in THIS image's caption, purpose, placement or observations, and contradictions with the article. "
            "Describe what is visible. Reject misleading captions, topic mismatch, fabricated screenshot/"
            "firsthand claims, unreadable necessary details, and unsupported observations. For official captures, reject any visible personal data, account identity, authentication information, fabricated UI, or claims not visible in the supplied pixels. A source URL, timestamp or privacy declaration alone never proves the pixels are authentic or safe. Generated examples "
            "are allowed when honestly labeled. Separate optional aesthetic preferences and perfectly identical composition from substantive reader claims; uncertainty whether an illustrative figure is a mannequin or a person alone is not rejection evidence when no real-photography or firsthand-wear claim is made. Still reject visible failures of claimed solid color, subject type, hem/sock exposure, or caption promises. Return passed only when no substantive issues remain.\n" +
            json.dumps({"imageIndex": index, "plan": plan, "publicationPlans": plans, "context": context}, ensure_ascii=False))
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

async def annotate_observed_materials(packet=None, observations=None, *args, **kwargs):
    if not packet:
        return {}
    packet = _capture_packet(packet)
    rows = packet['materials']
    verify_visual_records(rows, [row['filePath'] for row in rows], observations, source_observations=True)
    # Preserve the reviewed row/bytes exactly; no generated overlays or rewritten UI.
    return packet
