"""Bind answer review to the original question and the actual manuscript."""

TITLE_ANSWER_POLICY = "제목의 질문과 독자의 검색 의도를 명쾌하게 해결하는 본문을 작성한다."


def answer_review_inputs(question, article):
    if not isinstance(question, str) or not question.strip() or not isinstance(article, dict):
        raise RuntimeError("Answer review question or manuscript missing")
    title, blocks = article.get("title"), article.get("blocks")
    if (not isinstance(title, str) or not title.strip() or not isinstance(blocks, list)
            or not blocks or any(not isinstance(block, dict) or not isinstance(block.get("text"), str)
                                 or not block["text"].strip() for block in blocks)):
        raise RuntimeError("Answer review title or body missing")
    return {"readerQuestion": question, "title": title,
            "readerTask": article.get("readerTask"), "blocks": blocks}


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


def validate_answer_audit(audit, inputs):
    if (not isinstance(inputs, dict) or not inputs.get("readerQuestion")
            or not inputs.get("title") or not inputs.get("blocks")):
        raise RuntimeError("Answer review requires actual manuscript inputs")
    if not isinstance(audit, dict) or any(audit.get(key) is not True for key in ("titleMatches", "intentResolved")):
        raise RuntimeError("Answer review failed or incomplete")
    return True


def canonicalize_answer_audit(audit=None, *args, **kwargs):
    """Preserve the model verdict; absent evidence cannot become approval."""
    if not isinstance(audit, dict):
        raise RuntimeError("Answer audit missing")
    return audit
