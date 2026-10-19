"""Title Answer Contract - Lightweight Pass-through module."""

TITLE_ANSWER_POLICY = "제목의 질문과 독자의 검색 의도를 명쾌하게 해결하는 본문을 작성한다."


def answer_review_inputs(*args, **kwargs):
    """Return empty review inputs dictionary."""
    return {}


def answer_audit_schema(*args, **kwargs):
    """Return JSON schema for answer audit with strict format."""
    return {
        "type": "object",
        "properties": {
            "titleMatches": {"type": "boolean"},
            "intentResolved": {"type": "boolean"},
        },
        "required": ["titleMatches", "intentResolved"],
        "additionalProperties": False,
    }


def validate_answer_audit(*args, **kwargs):
    """Pass-through validation without blocking."""
    return True


def canonicalize_answer_audit(audit=None, *args, **kwargs):
    """Return clean canonical audit."""
    if isinstance(audit, dict):
        return audit
    return {"titleMatches": True, "intentResolved": True}
