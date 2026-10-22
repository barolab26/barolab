"""Aggregate provider-reported usage only; never store prompts or credentials."""
import datetime as dt
from pathlib import Path

from common.collection_observability import locked, write

ROOT=Path(__file__).resolve().parents[1]
KST=dt.timezone(dt.timedelta(hours=9))


def record_codex_usage(events, model, root=ROOT, now=None):
    import json
    now=now or dt.datetime.now(KST)
    day=now.astimezone(KST).date().isoformat()
    reports=[e.get('usage') for e in events if e.get('type')=='turn.completed']
    reports=[u for u in reports if isinstance(u,dict) and
             all(type(u.get(k)) is int and u[k]>=0 for k in ('input_tokens','output_tokens'))]
    if not reports:return
    path=Path(root)/'server/data/llm-usage.json'
    path.parent.mkdir(parents=True,exist_ok=True)
    with locked(path.with_suffix('.lock')):
        try:state=json.loads(path.read_text(encoding='utf-8'))
        except (OSError,ValueError):state={}
        if state.get('date')!=day:state={'date':day,'totalTokens':0,'byModel':{},'calls':0}
        count=sum(u['input_tokens']+u['output_tokens'] for u in reports)
        state['totalTokens']+=count
        state['byModel'][model]=state['byModel'].get(model,0)+count
        state['calls']+=len(reports)
        state.update(schema='barolab-llm-usage-v1',scope='codex_cli_reported_usage',
                     checkedAt=now.isoformat(),coverageStartedAt=state.get('coverageStartedAt') or now.isoformat())
        write(path,state)
