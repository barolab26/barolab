"""Ego Lite's bounded execution surface for the existing claimed staff queue."""
from datetime import datetime, timezone
import logging


def execute_staff_action(action, *, task_id, request_id, observer=None, requester='jarvis', parent_request_id='unknown'):
    from server.agent_tools import validate_staff_actions, execute_agent_tool

    checked = validate_staff_actions([action])[0]
    if not isinstance(task_id, str) or not task_id or not isinstance(request_id, str) or not request_id:
        raise ValueError('Claimed staff execution identity required')
    started = datetime.now(timezone.utc).isoformat()
    receipt = {'executor': 'ego-lite', 'taskId': task_id, 'requestId': request_id,
               'agent': checked['agent'], 'tool': checked['tool'],
               'startedAt': started, 'finishedAt': None, 'status': 'running', 'completed': False}
    def notify():
        if observer:
            try:
                observer(dict(receipt))
            except Exception as exc:
                logging.getLogger(__name__).warning('Ego execution telemetry unavailable: %s', type(exc).__name__)
    notify()
    try:
        from common.ego_telemetry import execution_context
        with execution_context(task_id=task_id, request_id=request_id, requester=requester,
                               actor=checked['agent'], tool=checked['tool'], parent_request_id=parent_request_id, source='staff_queue'):
            result = execute_agent_tool(checked['agent'], checked['tool'], **checked['args'])
        if not isinstance(result, dict):
            raise ValueError('Registered tool returned no structured receipt')
    except Exception as exc:
        result = {'ok': False, 'status': 'failed', 'errorType': type(exc).__name__}
    status = result.get('status') or ('returned' if result.get('ok') is True else 'unknown')
    pending = status in ('running', 'started', 'queued', 'awaiting_completion', 'unknown')
    returned = datetime.now(timezone.utc).isoformat()
    receipt.update(returnedAt=returned, finishedAt=None if pending else returned,
                   status=status, completed=not pending)
    notify()
    return {**result, 'executorReceipt': receipt}
