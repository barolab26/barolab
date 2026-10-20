"""Conservative retry decisions from recorded, comparable content inputs."""
import hashlib
import json
import re

PLANNING_ARTIFACT_NAMES = ("research.md", "keywords.md", "draft.md")

def valid_hash(value):
    return isinstance(value, str) and bool(re.fullmatch(r"[0-9a-f]{64}", value))

def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

def material_content_hash(packet=None):
    return _hash(packet) if packet else ""

def material_bytes_hash(packet=None):
    rows = (packet or {}).get("materials", [])
    hashes = [row.get("sha256") for row in rows]
    if not hashes or not all(valid_hash(value) for value in hashes):
        return ""
    return _hash(hashes)

def build_recovery_context(account, options=None, packet=None, content_quality_sha=None, routing=None):
    options = options or {}
    inputs = {key: options.get(key) for key in ("topic_seed", "main_keyword", "materials_manifest", "evidence_dir")}
    inputs["bridge_source_urls"] = sorted(set(options.get("bridge_source_urls") or []))
    result = {"account": account, "requestedContentInputsSha256": _hash(inputs),
        "requestedTopicSeed": options.get("topic_seed"),
        "contentQualitySha256": content_quality_sha, "routingPolicySha256": routing,
        "materialsManifestSha256": (packet or {}).get("manifestSha256", ""),
        "materialPresenceKnown": True, "hadMaterials": bool(packet),
        "materialContentSha256": material_content_hash(packet),
        "materialBytesSha256": material_bytes_hash(packet),
        "readerQuestion": (packet or {}).get("readerQuestion", "")}
    result["sha256"] = _hash(result)
    return result

def _previous(attempt, legacy):
    value = (attempt or {}).get("recoveryContext")
    if not isinstance(value, dict) and legacy:
        value = legacy(attempt)
    return value if isinstance(value, dict) else {}

def attempt_context_changed(latest, context, legacy=None):
    previous = _previous(latest, legacy)
    if previous.get("account") != context.get("account"):
        return False
    # Unknown old values cannot prove a change or reset the retry budget.
    return any(valid_hash(previous.get(key)) and valid_hash(context.get(key))
        and previous[key] != context[key] for key in (
            "requestedContentInputsSha256", "contentQualitySha256", "routingPolicySha256",
            "materialContentSha256", "materialBytesSha256"))

def scoped_automatic_attempts(relevant, context, legacy=None):
    return [row for row in relevant if row.get("runMode") in ("catch_up", "daily")
            and not attempt_context_changed(row, context, legacy)]

def material_context_ready(latest=None, context=None, legacy=None):
    context = context or {}
    previous = _previous(latest, legacy)
    return (previous.get("account") == context.get("account")
        and previous.get("materialPresenceKnown") is True
        and context.get("hadMaterials") is True
        and valid_hash(context.get("materialContentSha256"))
        and valid_hash(context.get("materialBytesSha256"))
        and (previous.get("hadMaterials") is False or
             (valid_hash(previous.get("materialBytesSha256"))
              and previous["materialBytesSha256"] != context["materialBytesSha256"])))

def question_context_ready(latest=None, context=None, legacy=None):
    context = context or {}
    previous = _previous(latest, legacy)
    before = previous.get("requestedTopicSeed")
    after = context.get("requestedTopicSeed")
    return (previous.get("account") == context.get("account")
        and "requestedTopicSeed" in previous and isinstance(after, str) and bool(after.strip())
        and after.strip() != str(before or "").strip())

def make_planning_reclassification(attempt=None, artifacts=None, now_str=None):
    raise ValueError("Planning failure reclassification requires a verified audit implementation")

def project_planning_reclassification(attempt=None, artifacts=None, audit=None):
    raise ValueError("Unverified planning reclassification cannot alter retry eligibility")
