"""Bounded action observations; never authorization or input-content capture."""
import contextvars
import hashlib
import json
import logging
import os
import re
import threading
import time
import uuid
from contextlib import contextmanager, asynccontextmanager
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path

ENV_KEY = 'BAROLAB_EGO_CONTEXT'
DIRECTORY = Path.home() / '.barolab' / 'ego-telemetry'
_context = contextvars.ContextVar('ego_context', default=None)
_lock = threading.Lock()
_fields = {'task_id':'taskId', 'request_id':'requestId', 'requester':'requester',
           'actor':'actor', 'project':'project', 'parent_request_id':'parentRequestId', 'source':'source', 'tool':'tool'}
_safe = re.compile(r'[A-Za-z0-9_:.-]{1,180}')
ACTIONS = {'tool','click','type','press','upload','insert_text','navigate','download','api_request'}
TARGETS = {'registered-tool','naver-editor','naver-title','naver-body','naver-toolbar','naver-link',
           'naver-image','naver-caption','naver-sticker','naver-editor-key','kin-editor','kin-answer',
           'kin-submit','kin-editor-key','search-results','official-source','flow-home','flow-settings',
           'flow-single-output','flow-new-project','flow-project-tile','flow-generate','flow-dismiss',
           'flow-prompt','flow-image','cf-image-upload','cf-post-submit',
           'naver-search','naver-search-query','naver-search-submit',
           'threads-scheduler','threads-publish','threads-api-read','threads-api-write',
           'threads-reconcile','threads-recovery','threads-measurement','threads-authoring',
           'metrics-collection','revenue-collection','traffic-collection','maintenance-audit',
           'maintenance-prepare','maintenance-apply','maintenance-run','metrics-browser','metrics-auth'}


def current_context():
    value = _context.get()
    if value is not None:
        return dict(value)
    try:
        value = json.loads(os.environ.get(ENV_KEY, '{}'))
        if not isinstance(value, dict) or set(value) - (set(_fields.values()) | {'source'}):
            raise ValueError('Invalid execution context')
        if any(not isinstance(v, str) or not _safe.fullmatch(v) for v in value.values()):
            raise ValueError('Invalid execution identity')
        if value.get('taskId'):
            return value
    except (ValueError, TypeError):
        pass
    return {'taskId': 'direct:' + str(os.getpid()), 'requester': 'unknown', 'actor': 'unknown', 'source': 'direct'}


@contextmanager
def execution_context(**fields):
    value = current_context()
    for key, item in fields.items():
        if key not in _fields or not isinstance(item, str) or not _safe.fullmatch(item):
            logging.getLogger(__name__).warning('Invalid Ego context field omitted')
            continue
        value[_fields[key]] = item
    token = _context.set(value)
    try:
        yield value
    finally:
        _context.reset(token)


def export_environment(env=None):
    result = dict(os.environ if env is None else env)
    result[ENV_KEY] = json.dumps(current_context(), separators=(',', ':'))
    return result


def _record(name, target, count, phase, action_id):
    try:
        # These are static labels, never selectors, URLs, typed strings or errors.
        if name not in ACTIONS or target not in TARGETS:
            return
        if count is not None and (type(count) is not int or not 0 <= count <= 1_000_000):
            return
        context = current_context()
        event = {'actionId':action_id, 'action':name, 'target':target, 'phase':phase,
                 'at':datetime.now(timezone.utc).isoformat()}
        if count is not None:
            event['count'] = count
        # A child preserves task identity but never races its parent's snapshot file.
        key = hashlib.sha256((context['taskId'] + ':' + str(os.getpid())).encode()).hexdigest()
        with _lock:
            DIRECTORY.mkdir(parents=True, exist_ok=True)
            path = DIRECTORY / (key + '.json')
            recent = []
            if path.is_file() and path.stat().st_size < 100000:
                try:
                    recent = json.loads(path.read_text(encoding='utf-8')).get('recent', [])
                except (ValueError, OSError):
                    pass
            payload = {'context':context, 'processId':os.getpid(), 'latest':event,
                       'recent':(recent + [event])[-16:], 'observedAt':event['at']}
            temporary = path.with_suffix('.' + str(os.getpid()) + '.' + str(time.time_ns()) + '.tmp')
            try:
                temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
                os.replace(temporary, path)
            finally:
                temporary.unlink(missing_ok=True)
    except Exception as exc:
        logging.getLogger(__name__).warning('Ego action observation unavailable: %s', type(exc).__name__)


@contextmanager
def action(name, target, count=None):
    identity = uuid.uuid4().hex
    _record(name, target, count, 'before', identity)
    try:
        yield
    except BaseException:
        _record(name, target, count, 'failed', identity)
        raise
    else:
        _record(name, target, count, 'after', identity)


@asynccontextmanager
async def async_action(name, target, count=None):
    with action(name, target, count):
        yield


def observed_operation(project, target, *, requester='unknown'):
    """Observe a synchronous registered entry without changing its execution policy."""
    def decorate(function):
        @wraps(function)
        def wrapped(*args, **kwargs):
            current = current_context()
            fields = {'project': project}
            if current.get('taskId') == 'direct:' + str(os.getpid()):
                fields = {'task_id':'direct:' + uuid.uuid4().hex, 'project':project,
                          'requester':requester, 'actor':'unknown', 'source':'direct'}
            with execution_context(**fields), action('tool', target):
                return function(*args, **kwargs)
        return wrapped
    return decorate
