"""Ego Lite's bounded execution surface for the existing claimed staff queue."""
from datetime import datetime, timezone


def execute_staff_action(action, *, task_id, request_id):
    from server.agent_tools import validate_staff_actions, execute_agent_tool

    checked = validate_staff_actions([action])[0]
    if not isinstance(task_id, str) or not task_id or not isinstance(request_id, str) or not request_id:
        raise ValueError('Claimed staff execution identity required')
    started = datetime.now(timezone.utc).isoformat()
    try:
        result = execute_agent_tool(checked['agent'], checked['tool'], **checked['args'])
        if not isinstance(result, dict):
            raise ValueError('Registered tool returned no structured receipt')
    except Exception as exc:
        result = {'ok': False, 'status': 'failed', 'errorType': type(exc).__name__}
    status = result.get('status') or ('returned' if result.get('ok') is True else 'unknown')
    pending = status in ('running', 'started', 'queued', 'awaiting_completion', 'unknown')
    return {**result, 'executorReceipt': {
        'executor': 'ego-lite', 'taskId': task_id, 'requestId': request_id,
        'startedAt': started, 'finishedAt': datetime.now(timezone.utc).isoformat(),
        'status': status, 'completed': not pending,
    }}
