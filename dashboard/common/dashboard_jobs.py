"""Private shared-file requests between the NAS dashboard and Windows workers."""
import datetime as dt
import json
import os
from pathlib import Path
import re
import threading
import uuid
import time

ROOT = Path(__file__).resolve().parents[2]
JOBS = ROOT / 'dashboard' / 'data' / 'control-jobs'
LOCK = threading.Lock()


def stamp():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def write(path, data, *, durable=False):
    if Path(path).name == 'automation-journal.json' and isinstance(data, dict):
        attempts = data.get('attempts') or []
        latest = attempts[-1] if attempts else {}
        if latest.get('phase') == 'started' and latest.get('submissionStarted') is False and 'preCommitIntent' not in latest:
            data = {**data, 'attempts': [*attempts[:-1], {**latest, 'preCommitIntent': False}]}
    submission = isinstance(data, dict) and data.get('submissionStatus') == 'submitting'
    if submission:
        data = {**data, 'preCommitIntent': True}
    atomic_text(path, json.dumps(data, ensure_ascii=False, indent=2), durable=submission or durable)


def atomic_text(path, content, *, durable=False):
    """Publish a complete file despite brief Windows/SMB reader locks."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temporary.open('w', encoding='utf-8') as handle:
            handle.write(content)
            if durable:
                handle.flush()
                os.fsync(handle.fileno())
        for attempt in range(20):
            try:
                os.replace(temporary, path)
                if durable:
                    descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
                    try:os.fsync(descriptor)
                    finally:os.close(descriptor)
                break
            except PermissionError:
                if attempt == 19:
                    raise
                time.sleep(0.15)
    finally:
        temporary.unlink(missing_ok=True)


def path(job_id):
    if not re.fullmatch(r'[a-f0-9]{32}', str(job_id)):
        raise ValueError('잘못된 작업 ID입니다.')
    return JOBS / (job_id + '.json')


def load(job_id):
    return json.loads(path(job_id).read_text(encoding='utf-8'))


def pending(kind):
    if not JOBS.exists():
        return []
    jobs = []
    for file in JOBS.glob('*.json'):
        data = json.loads(file.read_text(encoding='utf-8'))
        if data.get('kind') == kind and data.get('status') == 'pending':
            jobs.append(data)
    return sorted(jobs, key=lambda job: job['createdAt'])


def enqueue(kind, payload):
    if kind not in ('codex-test', 'cf-retry', 'growth-radar', 'growth-doctor'):
        raise ValueError('지원하지 않는 작업입니다.')
    with LOCK:
        if kind in ('cf-retry', 'growth-radar', 'growth-doctor'):
            for job in pending(kind):
                if job['payload'] == payload:
                    return job
        job = {'id': uuid.uuid4().hex, 'kind': kind, 'payload': payload,
               'status': 'pending', 'createdAt': stamp()}
        write(path(job['id']), job)
        return job


def finish(job, result=None, error=None):
    job.update(status='failed' if error else 'succeeded', finishedAt=stamp())
    if error:
        job['error'] = str(error)[:500]
    else:
        job['result'] = result
    write(path(job['id']), job)


def public(job):
    return {key: job[key] for key in ('id', 'kind', 'status', 'createdAt', 'finishedAt', 'error') if key in job}
