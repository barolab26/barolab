"""Legacy bounded-draft API routed to Codex while AGY is disabled."""
import time

from common import codex_cli, llm_settings


def compact_policy(text: str, max_chars: int = 900) -> str:
    """Diet bloated policy strings to core rules while preserving essential constraints."""
    if not isinstance(text, str) or not text.strip():
        return ''
    lines = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        # Skip verbose examples ("예를 들어 ...") to keep only core rules
        if line.startswith(('예를 들어', '이 예문을')):
            continue
        lines.append(line)
    compacted = '\n'.join(lines)
    if len(compacted) <= max_chars:
        return compacted
    return compacted[:max_chars].rsplit('\n', 1)[0].strip()



def generate(router, task, level='standard', run=None):
    """Keep legacy callers working without ever launching the exhausted AGY CLI."""
    model = llm_settings.load()['providers'].get('codex', {}).get('model') or 'gpt-6.1-sol'
    start = time.monotonic()
    entry = dict(provider='codex', requested_model=model, returned_model='unknown', attempt=1, status='failed')
    try:
        prompt = (
            'Return only a bounded draft in the draft JSON field, without tools, filesystem access or shell commands. '
            'Do not execute or apply changes. All output needs supervisor review.\n' + router.prepare(task)
        )
        response, actual_model = codex_cli.generate(prompt, model, response_schema={
            'type': 'object', 'properties': {'draft': {'type': 'string'}},
            'required': ['draft'], 'additionalProperties': False,
        })
        entry['returned_model'] = actual_model
        draft = response.get('draft')
        if not isinstance(draft, str) or not draft.strip() or len(draft) > 24000:
            raise ValueError('codex_invalid_draft')
        entry['status'] = 'ok'
        return router.redact(draft)
    finally:
        entry['latency_ms'] = round((time.monotonic() - start) * 1000)
        router.ledger(entry)
